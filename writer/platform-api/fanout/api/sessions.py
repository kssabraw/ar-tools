"""Session endpoints: silo discovery (M2) + keyword pipeline (M3/M4).

Lifecycle: create a session (grounding + proposal), optionally resolve
disambiguation, review/edit silos, finalize (embeds each silo), pick which silos
to deep-mine (§7.2), then run /expand — which now runs the full refinement
pipeline: expansion + competitor mining + relevance gate + statistical clustering.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from fanout import cancellation, jobs
from fanout.auth import AuthedUser, get_role, require_owner, require_user
from fanout.config import get_settings
from fanout.cost import estimate_cost, requires_approval
from fanout.cost_attribution import metered_sync
from fanout.dataforseo import get_dataforseo
from fanout.llm import LLMError, active_embedding_model, get_llm
from fanout.logging import bind_session_id
from fanout.pipeline.models import PROPOSABLE_TYPES, RelationshipType
from fanout.pipeline.orchestrate import (
    cluster_preview,
    routing_diagnostic,
    simulate_best_silo_clustering,
)
from fanout.pipeline.recursive_fanout import count_sub_anchors, derive_sub_anchors
from fanout.pipeline.silo_anchor import build_enriched_anchors
from fanout.pipeline.silo_discovery import run_silo_discovery
from fanout.storage import silo as store

logger = logging.getLogger(__name__)
router = APIRouter(tags=["sessions"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------
class CreateSessionBody(BaseModel):
    seed_keyword: str = Field(min_length=1, max_length=200)
    project_id: str | None = None
    # AR Tools client this run belongs to (client-scoped runs). Optional — a run
    # created outside a client context (the global/owner view) leaves it null.
    client_id: str | None = None
    audience_hint: str | None = None
    disambiguation_hint: str | None = None
    topic_count: int = Field(default=5, ge=3, le=10)
    coverage_mode: str = Field(default="standard", pattern="^(standard|comprehensive)$")
    # Intended content type for this run, chosen up front in the new-session flow
    # so the writer/scheduler defaults to it later. The keyword pipeline itself is
    # content-type agnostic; this is carried on the session (in `settings`) and
    # used to seed the Schedule modal. `local_seo_page` needs a client-linked
    # session + a target location at schedule time.
    content_type: str = Field(default="blog_post", pattern="^(blog_post|local_seo_page)$")
    # Local SEO target area, chosen on the new-session form (Service + location
    # typeahead, mirroring the Local SEO writer). Carried on the session (in
    # `settings`) so the Schedule modal pre-fills it. Ignored for blog runs; the
    # keyword pipeline itself is location-agnostic beyond `location_code`.
    location: str | None = Field(default=None, max_length=200)
    recursive_fanout: bool = False
    # Per-country locale (E1, 2026-06-17). DataForSEO location_code for the
    # session's market; validated against the supported English-market set in the
    # endpoint. Default US (2840).
    location_code: int = Field(default=2840)
    # §7.8 metrics enrichment toggle. None -> use workspace default
    # (`enrich_with_metrics_default`, currently True). Surfacing as Optional
    # rather than bool=True so a deployed default flip propagates to clients
    # that don't send the field.
    enrich_with_metrics: bool | None = None


class DisambiguateBody(BaseModel):
    choice: str = Field(min_length=1, max_length=200)


class OverrideAudienceBody(BaseModel):
    detected_audience: str = Field(min_length=1, max_length=400)


class AddTopicBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    rationale: str | None = None
    relationship_type: RelationshipType = RelationshipType.property_or_mechanism
    is_broader_class: bool = False


class EditTopicBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    rationale: str | None = None
    relationship_type: RelationshipType | None = None


class RegateBody(BaseModel):
    # Optional per-call overrides so threshold + clustering granularity can be
    # tuned without changing the Railway env. Omitted values fall back to config.
    relevance_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    clustering_edge_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    clustering_resolution: float | None = Field(default=None, gt=0.0, le=20.0)
    # Hard cap on active keywords per silo (post-gate, top-N by relevance). 0 =
    # no cap. Owner-only override; the env default is `active_per_silo_cap`.
    active_per_silo_cap: int | None = Field(default=None, ge=0, le=50000)
    # Peer-entity filter overrides (for testing on sessions whose grounding ran
    # before this existed). Omitted -> use the session's stored lists.
    aliases: list[str] | None = None
    peer_entities: list[str] | None = None


class FanoutBody(BaseModel):
    # Recursive Fanout (PRD §7.7). RF is a 5x-8x cost step, so it will not spend
    # unless `confirm_cost` is true — an unconfirmed call returns the cost
    # estimate and the sub-anchor plan instead of starting. (The VA approval
    # workflow is M9; until then owner-direct runs gate on this explicit flag.)
    confirm_cost: bool = False
    # Same per-call gate/clustering overrides as /regate (the enlarged pool is
    # gated + clustered after the recursive expansion).
    relevance_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    clustering_edge_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    clustering_resolution: float | None = Field(default=None, gt=0.0, le=20.0)
    active_per_silo_cap: int | None = Field(default=None, ge=0, le=50000)
    aliases: list[str] | None = None
    peer_entities: list[str] | None = None


class RoutingDiagnosticBody(BaseModel):
    # Probe keywords to route under each candidate silo-anchor strategy.
    probes: list[str] = Field(min_length=1, max_length=50)
    active_sample_per_topic: int = Field(default=80, ge=1, le=400)


class ClusterPreviewBody(BaseModel):
    # Granularity sweep: gate once, then report cluster stats for each
    # (edge_threshold, resolution) config. Read-only — nothing is persisted.
    relevance_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    configs: list[tuple[float, float]] = Field(
        default_factory=lambda: [(0.55, 1.0), (0.7, 1.0), (0.75, 1.5), (0.8, 2.0)],
        max_length=12,
    )


class DeepMineBody(BaseModel):
    # Silos the user chose to mine for competitor keywords (PRD §7.2). The seed
    # is always mined regardless; an empty list means "seed only".
    topic_ids: list[str] = Field(default_factory=list)


class ApprovalDecisionBody(BaseModel):
    # Optional Owner note attached on approve/reject (PRD §11.3 step 5).
    note: str | None = Field(default=None, max_length=2000)


class SiloDiscoveryResponse(BaseModel):
    session_id: str
    status: str
    seed_keyword: str | None = None
    detected_audience: str | None = None
    needs_disambiguation: bool = False
    interpretations: list[str] = []
    degraded_notes: list[str] = []
    silos: list[dict] = []
    site_base_url: str | None = None
    # Intended content type chosen at session creation (lives in `settings`); the
    # Schedule modal seeds from it. Null/absent -> treat as blog_post.
    content_type: str | None = None
    # Local SEO target area chosen at session creation (lives in `settings`); the
    # Schedule modal pre-fills its location from it. Null for blog runs.
    location: str | None = None
    publish_config: dict = {}
    publish_available: dict = {}     # which destinations have server creds (no secrets)


class LocationSuggestion(BaseModel):
    location_name: str
    location_code: int
    location_type: str = ""
    country_iso_code: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _require_session(user: AuthedUser, session_id: str) -> dict:
    session = store.session_visible_to_user(user.access_token, session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return session


def _assert_embedding_current(session: dict) -> None:
    """Refuse an embedding-dependent re-op on a session whose stored vectors were
    produced by a different embedding model than the active one (freeze-old-sessions
    rule, 2026-06-15). text-embedding-3-small and gemini-embedding-001 are both
    1536-dim but in different spaces, so re-processing would silently mix them.
    During the dormant period (active == OpenAI) this is a no-op for every session.
    """
    active = active_embedding_model()
    tagged = session.get("embedding_model") or "text-embedding-3-small"
    if tagged != active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"This session's vectors were built with '{tagged}', but the app now "
                f"embeds with '{active}'. Re-processing would mix incompatible vector "
                "spaces. Start a new session — existing sessions are read-only for "
                "embedding operations after an embedding-provider change."
            ),
        )


def _require_cluster(user: AuthedUser, cluster_id: str) -> tuple[dict, str]:
    """Resolve a cluster and verify the caller may edit it (via its session's RLS).
    Returns (cluster, session_id)."""
    cluster = store.get_cluster(cluster_id)
    if not cluster:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cluster not found")
    sid = store.cluster_session_id(cluster_id)
    if not sid:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cluster not found")
    _require_session(user, sid)
    return cluster, sid


def _require_gap(user: AuthedUser, gap_id: str) -> dict:
    gap = store.get_gap(gap_id)
    if not gap:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gap not found")
    topic = store.get_topic(gap["topic_id"])
    if not topic:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gap not found")
    _require_session(user, topic["session_id"])
    return gap


def _resolve_peer_terms(session: dict, body) -> tuple[list[str], list[str]]:
    """Seed terms (seed + aliases) and peer terms for the peer-entity filter.
    Request-body overrides win (for sessions whose grounding predates the lists),
    else use what grounding stored on the session."""
    seed = session.get("seed_keyword") or ""
    aliases = body.aliases if getattr(body, "aliases", None) is not None else (session.get("aliases") or [])
    peers = body.peer_entities if getattr(body, "peer_entities", None) is not None else (session.get("peer_entities") or [])
    seed_terms = [t for t in [seed, *aliases] if t]
    return seed_terms, list(peers)


def _estimate_for_session(
    session: dict, gated_count: int | None, *, topics: list | None = None
) -> dict:
    """Cost estimate + approval-gate decision for a session (PRD §8.1 / §8.4).
    `gated_count` lets the wizard preview a not-yet-persisted deep-mine selection;
    when None, the persisted gated-topic count is used. `topics` lets a caller that
    already fetched the silos pass them in to avoid a redundant read (e.g. /expand);
    omit it to fetch. Approval is needed for a VA when the estimate exceeds the
    workspace soft cap OR recursive fanout is on."""
    settings = session.get("settings") or {}
    if topics is None:
        topics = store.list_topics(session["id"])
    silo_count = len(topics)
    gated = (
        gated_count
        if gated_count is not None
        else store.count_gated_topics(session["id"])
    )
    recursive = bool(settings.get("recursive_fanout"))
    estimate = estimate_cost(
        coverage_mode=settings.get("coverage_mode", "standard"),
        silo_count=silo_count,
        deep_mine_count=gated,
        recursive_fanout=recursive,
        enrich_with_metrics=bool(settings.get("enrich_with_metrics")),
    )
    ws = store.get_workspace_settings()
    soft_cap = float(ws.get("va_soft_cap_usd") or 0.0)
    needs_approval, triggers = requires_approval(
        estimated_cost_usd=estimate.total_usd,
        soft_cap_usd=soft_cap,
        recursive_fanout=recursive,
    )
    return {
        "session_id": session["id"],
        "estimated_cost_usd": estimate.total_usd,
        "breakdown": estimate.breakdown,
        "recursive_multiplier": estimate.recursive_multiplier,
        "silo_count": silo_count,
        "deep_mine_count": gated,
        "coverage_mode": settings.get("coverage_mode", "standard"),
        "recursive_fanout": recursive,
        "va_soft_cap_usd": soft_cap,
        "requires_approval": needs_approval,
        "approval_triggers": triggers,
    }


def _run_and_persist(session: dict) -> SiloDiscoveryResponse:
    """Run silo discovery for a session and persist the outcome."""
    settings = session.get("settings") or {}
    coverage_mode = settings.get("coverage_mode", "standard")
    bind_session_id(session["id"])
    try:
        # Silo discovery runs synchronously in the request (cheap LLM + DataForSEO
        # sample). Meter its cost into the session's running total so actual_cost
        # reflects the full §8.1 run, not just the background pipeline (§16.4).
        with metered_sync(session["id"], "silo_discovery"):
            result = run_silo_discovery(
                seed=session["seed_keyword"],
                topic_count=int(settings.get("topic_count", 5)),
                audience_hint=session.get("audience_hint"),
                disambiguation_hint=session.get("disambiguation_hint")
                or session.get("disambiguation_choice"),
                llm=get_llm(),
                dfs=get_dataforseo(store.session_location_code(session)),
                serp_top_n=10 if coverage_mode == "comprehensive" else 5,
                ambiguity_separation_threshold=get_settings().ambiguity_separation_threshold,
            )
    except LLMError as exc:
        store.update_session(session["id"], {"status": "error"})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Silo discovery could not complete: {exc}",
        ) from exc

    store.update_session(session["id"], {
        "detected_audience": result.detected_audience,
        "aliases": result.aliases,
        "peer_entities": result.peer_entities,
    })

    if result.needs_disambiguation:
        return SiloDiscoveryResponse(
            session_id=session["id"],
            status="running_pre_review",
            detected_audience=result.detected_audience,
            needs_disambiguation=True,
            interpretations=result.interpretations,
        )

    store.delete_topics_for_session(session["id"])
    topics = store.insert_proposed_topics(session["id"], result.silos)
    store.update_session(session["id"], {"status": "awaiting_silo_review"})
    return SiloDiscoveryResponse(
        session_id=session["id"],
        status="awaiting_silo_review",
        detected_audience=result.detected_audience,
        degraded_notes=result.degraded_notes,
        silos=store.list_topics(session["id"]) if topics is not None else [],
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post("/sessions", response_model=SiloDiscoveryResponse)
def create_session(
    body: CreateSessionBody, user: AuthedUser = Depends(require_user)
) -> SiloDiscoveryResponse:
    # A supplied project must be one the caller can see (RLS), else the session
    # would attach to a project they don't own (PRD §13).
    if body.project_id and not store.project_visible_to_user(
        user.access_token, body.project_id
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if body.location_code not in store.SUPPORTED_LOCATION_CODES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported location_code {body.location_code}",
        )
    project_id = store.resolve_project_id(user.id, body.project_id)
    session = store.create_session(
        user_id=user.id,
        project_id=project_id,
        client_id=body.client_id,
        seed_keyword=body.seed_keyword.strip(),
        audience_hint=body.audience_hint,
        disambiguation_hint=body.disambiguation_hint,
        location_code=body.location_code,
        settings={
            "topic_count": body.topic_count,
            "coverage_mode": body.coverage_mode,
            "content_type": body.content_type,
            "location": (body.location or "").strip() or None,
            "recursive_fanout": body.recursive_fanout,
            "enrich_with_metrics": (
                body.enrich_with_metrics
                if body.enrich_with_metrics is not None
                else get_settings().enrich_with_metrics_default
            ),
        },
    )
    bind_session_id(session["id"])
    return _run_and_persist(session)


@router.post("/sessions/{session_id}/disambiguate", response_model=SiloDiscoveryResponse)
def disambiguate(
    session_id: str, body: DisambiguateBody, user: AuthedUser = Depends(require_user)
) -> SiloDiscoveryResponse:
    session = _require_session(user, session_id)
    bind_session_id(session_id)
    session = store.update_session(session_id, {"disambiguation_choice": body.choice.strip()})
    return _run_and_persist(session)


@router.get("/sessions/{session_id}", response_model=SiloDiscoveryResponse)
def get_session(
    session_id: str, user: AuthedUser = Depends(require_user)
) -> SiloDiscoveryResponse:
    session = _require_session(user, session_id)
    bind_session_id(session_id)
    _s = get_settings()
    return SiloDiscoveryResponse(
        session_id=session_id,
        status=session["status"],
        seed_keyword=session.get("seed_keyword"),
        detected_audience=session.get("detected_audience"),
        silos=store.list_topics(session_id),
        site_base_url=session.get("site_base_url"),
        content_type=(session.get("settings") or {}).get("content_type"),
        location=(session.get("settings") or {}).get("location"),
        publish_config=session.get("publish_config") or {},
        publish_available={
            "github": bool(_s.github_publish_token),
            "drive": bool(_s.google_oauth_client_id and _s.google_oauth_refresh_token),
        },
    )


@router.get("/locations", response_model=list[LocationSuggestion])
async def search_locations(
    query: str,
    country: str | None = None,
    client_id: str | None = None,
    user: AuthedUser = Depends(require_user),
) -> list[LocationSuggestion]:
    """Location typeahead for the Local SEO new-session form (Service + location
    autocomplete, mirroring the Local SEO writer). DataForSEO location suggestions
    served by a thin /fanout wrapper so the fanout-frontend — mounted under /fanout
    — doesn't reach a suite path outside its prefix.

    Scoped by `country` (ISO-2, from the form's selected market) when given, else
    by the client's country (`client_id`). The country path needs no client, so the
    field autocompletes even on a non-client run. Best-effort: returns [] on a short
    query, no scope, or any lookup failure rather than erroring the form."""
    if len((query or "").strip()) < 2:
        return []
    try:
        # Lazy import: the suite services live in platform-api, which mounts this
        # fanout app — import at call time to avoid an import-order coupling.
        from services import local_seo_service, locations_service

        if country:
            # An explicit country short-circuits client-country inference, so an
            # empty client dict is sufficient.
            rows = await locations_service.search_locations({}, query, country=country)
        elif client_id:
            rows = await local_seo_service.search_locations(client_id, query)
        else:
            return []
    except Exception:
        logger.exception(
            "fanout.locations.search failed country=%s client_id=%s", country, client_id
        )
        return []
    return [LocationSuggestion(**row) for row in rows]


@router.patch("/sessions/{session_id}/audience", response_model=SiloDiscoveryResponse)
def override_audience(
    session_id: str, body: OverrideAudienceBody, user: AuthedUser = Depends(require_user)
) -> SiloDiscoveryResponse:
    session = _require_session(user, session_id)
    bind_session_id(session_id)
    session = store.update_session(
        session_id, {"detected_audience": body.detected_audience.strip()}
    )
    return SiloDiscoveryResponse(
        session_id=session_id,
        status=session["status"],
        detected_audience=session.get("detected_audience"),
        silos=store.list_topics(session_id),
    )


@router.post("/sessions/{session_id}/finalize")
def finalize_silos(session_id: str, user: AuthedUser = Depends(require_user)) -> dict:
    session = _require_session(user, session_id)
    bind_session_id(session_id)
    topics = store.list_topics(session_id)
    if not topics:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No silos to finalize. Add at least one silo first.",
        )

    seed = session["seed_keyword"]
    audience = session.get("detected_audience") or ""
    # Rationale-anchor string per PRD §7.1.4: seed + rationale + audience.
    rationale_texts = [
        " ".join(part for part in (seed, t.get("rationale") or "", audience) if part).strip()
        for t in topics
    ]
    s = get_settings()
    llm = get_llm()
    try:
        rationale_vectors = llm.embed(rationale_texts)
    except LLMError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Embedding the silos failed. Try finalizing again.",
        ) from exc
    rationale_by_id = {t["id"]: v for t, v in zip(topics, rationale_vectors)}

    # Enriched silo anchors (routing calibration): LLM-generate ~N example
    # keywords per silo and centroid their embeddings with the rationale. Strictly
    # additive — a silo for which generation fails keeps its rationale anchor.
    example_counts: dict[str, int] = dict.fromkeys((t["id"] for t in topics), 0)
    if s.enriched_silo_anchor:
        anchors_by_id, example_counts = build_enriched_anchors(
            seed=seed,
            silos=topics,
            rationale_embeddings=rationale_by_id,
            peer_terms=session.get("peer_entities") or [],
            llm=llm,
            embed_fn=llm.embed,
            n=s.silo_anchor_example_count,
            max_workers=s.silo_anchor_max_workers,
        )
    else:
        anchors_by_id = rationale_by_id

    for topic in topics:
        store.set_topic_embedding(topic["id"], anchors_by_id[topic["id"]])

    logger.info(
        "step_complete",
        extra={"event": "step_complete", "step": "silo_finalize",
               "topic_count": len(topics),
               "examples_total": sum(example_counts.values()),
               "enriched": s.enriched_silo_anchor},
    )
    return {"finalized": True, "topic_count": len(topics)}


# ---- M4 deep-mine selection (PRD §7.2) ------------------------------------
@router.post("/sessions/{session_id}/deep-mine")
def set_deep_mine(
    session_id: str, body: DeepMineBody, user: AuthedUser = Depends(require_user)
) -> dict:
    """Record which silos to mine for competitor keywords. The seed is always
    mined; this only gates the additional silos."""
    _require_session(user, session_id)
    bind_session_id(session_id)
    valid_ids = {t["id"] for t in store.list_topics(session_id)}
    requested = list(dict.fromkeys(body.topic_ids))  # dedupe, preserve order
    invalid = [tid for tid in requested if tid not in valid_ids]
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Topics do not belong to this session: {', '.join(invalid)}",
        )
    # VA deep-mine cap (PRD §10.2 step 6 / §15.2 §7.2 #3): seed + N additional
    # silos. The seed is always mined and isn't in `requested`, so cap the list.
    if get_role(user) != "owner":
        cap = get_settings().va_deep_mine_max_silos
        if len(requested) > cap:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"VA mode can deep-mine at most the seed plus {cap} silos.",
            )
    store.set_topics_gating(session_id, requested)
    return {"gated_topic_ids": requested, "topics": store.list_topics(session_id)}


# ---- M3 expansion + M4 mining/relevance/clustering ------------------------
@router.post("/sessions/{session_id}/expand", status_code=status.HTTP_202_ACCEPTED)
def expand_session(session_id: str, user: AuthedUser = Depends(require_user)) -> dict:
    """Kick off the §7.3–§7.9 pipeline in the background and return immediately.
    The work runs past the 5-min edge cap, so the frontend polls
    GET /sessions/{id}/summary for status. The atomic run guard rejects a
    double-submit (409)."""
    session = _require_session(user, session_id)
    _assert_embedding_current(session)
    bind_session_id(session_id)
    topics = store.list_topics(session_id)
    if not topics:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No silos to expand. Finalize at least one silo first.",
        )
    # Cost estimate (PRD §8.1), computed for every run path: it both enforces the
    # VA approval gate (below) and is persisted for the §8.4 cost banner. Reuse the
    # silos we just fetched so the estimate doesn't re-read them.
    est = _estimate_for_session(session, None, topics=topics)
    # Approval gate, enforced server-side (PRD §8.4 / §11.3): a VA cannot start a
    # run that exceeds the workspace cost cap by calling /expand directly — it must
    # go through the approval workflow. The Owner's approve action kicks the run
    # via jobs.submit_expand (not this endpoint), so an approved run is unaffected.
    if get_role(user) != "owner" and est["requires_approval"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This run exceeds the workspace cost cap. Submit it for "
            "approval instead of running it directly.",
        )
    if not store.try_mark_running(session_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A pipeline run is already in progress for this session.",
        )
    # Persist the §8.1 estimate so the cost banner (§8.4) can compare estimate vs
    # the live actual on owner and under-cap VA runs — not only the approval path
    # (submit-for-approval persists its own; an owner-approved run keeps that one).
    # Best-effort: the run is already claimed (try_mark_running set status=running),
    # so a failed estimate write must NOT prevent submit_expand — otherwise the
    # session would strand as `running` with no job. The estimate is cosmetic (the
    # banner just loses its comparison line); the run itself is unaffected.
    try:
        store.update_session(
            session_id, {"estimated_cost_usd": est["estimated_cost_usd"]}
        )
    except Exception as exc:  # noqa: BLE001 — never strand the claimed run
        logger.warning(
            "estimate_persist_failed",
            extra={"event": "estimate_persist_failed", "reason": repr(exc)},
        )
    jobs.submit_expand(session_id)
    return {"status": "running", "session_id": session_id}


# ---- M9 cost estimate + approval workflow (PRD §8.4 / §11.3) --------------
@router.get("/workspace-settings")
def get_workspace_settings(user: AuthedUser = Depends(require_user)) -> dict:
    """Non-sensitive workspace settings (PRD §11.4) the wizard needs: the VA soft
    cap and the locked defaults. Any profiled user may read (matches the RLS
    SELECT policy); only the Owner can change them (a settings-update UI is out of
    M9 scope — values are managed in the DB for now)."""
    ws = store.get_workspace_settings()
    return {
        "va_soft_cap_usd": float(ws.get("va_soft_cap_usd") or 0.0),
        "owner_cost_confirm_threshold_usd": float(
            ws.get("owner_cost_confirm_threshold_usd") or 0.0
        ),
        "default_relevance_threshold": float(
            ws.get("default_relevance_threshold") or 0.0
        ),
    }


@router.get("/sessions/{session_id}/cost-estimate")
def cost_estimate(
    session_id: str,
    user: AuthedUser = Depends(require_user),
    gated_count: int | None = None,
) -> dict:
    """Estimate the run's cost from its config (PRD §8.1) and report whether it
    trips the approval gate (PRD §8.4). `gated_count` previews the wizard's
    not-yet-persisted deep-mine selection; omit it to use the persisted count."""
    session = _require_session(user, session_id)
    if gated_count is not None and gated_count < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="gated_count must be >= 0"
        )
    return _estimate_for_session(session, gated_count)


@router.post("/sessions/{session_id}/submit-for-approval")
def submit_for_approval(
    session_id: str, user: AuthedUser = Depends(require_user)
) -> dict:
    """Park a run at the approval gate (PRD §11.3 step 2): store the cost estimate,
    set status=pending_approval + approval_required, and DO NOT start the pipeline.
    The deep-mine selection must already be persisted (the wizard calls /deep-mine
    first, same as the run-now path). Allowed from a pre-run state — a fresh run
    after silo review, or a previously rejected run being resubmitted."""
    session = _require_session(user, session_id)
    bind_session_id(session_id)
    if session["status"] not in ("awaiting_silo_review", "rejected"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This session is not in a state that can be submitted for approval.",
        )
    if not store.list_topics(session_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Finalize at least one silo before submitting for approval.",
        )
    est = _estimate_for_session(session, None)
    store.update_session(
        session_id,
        {
            "status": "pending_approval",
            "approval_required": True,
            "estimated_cost_usd": est["estimated_cost_usd"],
            # Clear any decision from a prior reject so a resubmission is fresh.
            "approval_note": None,
            "approval_decided_by_user_id": None,
            "approval_decision_at": None,
        },
    )
    logger.info(
        "approval_submitted",
        extra={"event": "approval_submitted",
               "estimated_cost_usd": est["estimated_cost_usd"]},
    )
    return {"status": "pending_approval", **est}


@router.post("/sessions/{session_id}/cancel")
def cancel_running_session(
    session_id: str, user: AuthedUser = Depends(require_user)
) -> dict:
    """Cancel an in-progress pipeline run (expand / plan-articles / regate /
    fanout / architecture). Cooperative: flips status=cancelled atomically (so a
    second cancel races safely), signals the background worker via the
    cancellation registry, and the worker exits at its next external-call
    checkpoint (`raise_if_cancelled` at the top of each DataForSEO / OpenAI /
    Anthropic call). In-flight HTTP requests still bill — worst-case wait ≈ one
    DataForSEO timeout (60s) — but no new calls are made after the check fires.
    Partial metered spend persists (PRD §16.4 cost meter flushes on exit).
    Both roles, RLS-scoped — a VA can cancel their own session; the owner can
    cancel any visible session (§11.2 'VA can manage own sessions').
    Pending-approval sessions use /cancel-approval; only a `running` session is
    cancellable here."""
    _require_session(user, session_id)
    bind_session_id(session_id)
    # Atomic check-and-set so a second concurrent /cancel doesn't 409 the first
    # caller. If it returns False, the run wasn't running (already cancelled /
    # completed / never started).
    claimed = store.try_mark_cancelled(session_id)
    if not claimed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No pipeline run is in progress for this session.",
        )
    # Signal the worker. Setting after the DB flip is fine: the endpoint already
    # owns the status, and the next external-call checkpoint reads this to abort.
    cancellation.set_cancelled(session_id)
    logger.info("run_cancelled", extra={"event": "run_cancelled"})
    return {"status": "cancelled", "session_id": session_id}


@router.post("/sessions/{session_id}/cancel-approval")
def cancel_approval(
    session_id: str, user: AuthedUser = Depends(require_user)
) -> dict:
    """Withdraw a pending approval request (PRD §11.3 / §10.2 step 7 "cancel").
    Returns the session to the pre-run review state so the VA can adjust and
    resubmit or run a (now cheaper) configuration."""
    session = _require_session(user, session_id)
    bind_session_id(session_id)
    if session["status"] != "pending_approval":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No pending approval request to cancel.",
        )
    store.update_session(
        session_id, {"status": "awaiting_silo_review", "approval_required": False}
    )
    return {"status": "awaiting_silo_review", "session_id": session_id}


@router.get("/approvals")
def list_approvals(user: AuthedUser = Depends(require_owner)) -> list[dict]:
    """The Owner's approval queue (PRD §11.3 step 4): every session awaiting a
    decision, enriched with VA name, project, seed, settings, estimate, and the
    submitted-at time. Owner-only (§11.2: "Approve VA requests" is Owner-only; a VA
    cannot see another VA's queue)."""
    return store.list_pending_approvals()


@router.post("/sessions/{session_id}/approve")
def approve_session(
    session_id: str,
    body: ApprovalDecisionBody,
    user: AuthedUser = Depends(require_owner),
) -> dict:
    """Approve a pending run (PRD §11.3 step 6): record the decision, flip the
    session to running, and kick off the pipeline (the cost-bearing /expand, same
    entry point as a run-now session). Owner-only."""
    session = _require_session(user, session_id)
    bind_session_id(session_id)
    if session["status"] != "pending_approval":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This session is not awaiting approval.",
        )
    if not store.list_topics(session_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No silos to expand for this session.",
        )
    # Claim the run atomically (pending_approval -> running) before recording the
    # decision, so a double-approve can't double-spend.
    if not store.try_mark_running(session_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A run is already in progress for this session.",
        )
    store.update_session(
        session_id,
        {
            "approval_decided_by_user_id": user.id,
            "approval_decision_at": datetime.now(timezone.utc).isoformat(),
            "approval_note": (body.note or "").strip() or None,
        },
    )
    jobs.submit_expand(session_id)
    logger.info("approval_approved", extra={"event": "approval_approved"})
    return {"status": "running", "session_id": session_id}


@router.post("/sessions/{session_id}/reject")
def reject_session(
    session_id: str,
    body: ApprovalDecisionBody,
    user: AuthedUser = Depends(require_owner),
) -> dict:
    """Reject a pending run (PRD §11.3 step 7): record the decision + optional note
    and set status=rejected. The pipeline does not start. The VA sees the note and
    can adjust + resubmit. Owner-only."""
    session = _require_session(user, session_id)
    bind_session_id(session_id)
    if session["status"] != "pending_approval":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This session is not awaiting approval.",
        )
    store.update_session(
        session_id,
        {
            "status": "rejected",
            "approval_decided_by_user_id": user.id,
            "approval_decision_at": datetime.now(timezone.utc).isoformat(),
            "approval_note": (body.note or "").strip() or None,
        },
    )
    logger.info("approval_rejected", extra={"event": "approval_rejected"})
    return {"status": "rejected", "session_id": session_id}


@router.get("/sessions/{session_id}/summary")
def session_summary(session_id: str, user: AuthedUser = Depends(require_user)) -> dict:
    """Status + expansion/plan counts. Polled by the frontend to drive the UI and
    to resume a session on refresh; `plan` is null until the orchestrator runs."""
    _require_session(user, session_id)
    return store.get_pipeline_summary(session_id)


@router.get("/sessions/{session_id}/debug")
def session_debug(
    session_id: str, user: AuthedUser = Depends(require_owner)
) -> dict:
    """Owner debug view (PRD §15.3 #8 / §15.3 #7): the raw statistical clustering
    log + orchestrator decision log (merge/split/drop rationales, dedup
    collisions) + the cost attribution for any session. Owner-only — VAs cannot
    review orchestrator internals (§11.2); a VA gets 403 at the dependency layer.
    `_require_session` still scopes it to a session the caller can see."""
    _require_session(user, session_id)
    return store.get_session_debug(session_id)


@router.post("/sessions/{session_id}/regate", status_code=status.HTTP_202_ACCEPTED)
def regate_session(
    session_id: str, body: RegateBody, user: AuthedUser = Depends(require_owner)
) -> dict:
    """Kick off a re-gate (relevance gate + clustering) on the session's stored
    keyword pool at a (possibly overridden) threshold in the background, skipping
    DataForSEO. Returns immediately; poll GET /summary for status. A calibration
    tool: tune the threshold without re-paying for expansion + mining. Owner-only —
    it adjusts the relevance threshold, which VAs cannot (PRD §11.2)."""
    session = _require_session(user, session_id)
    _assert_embedding_current(session)
    bind_session_id(session_id)
    if not store.list_all_keyword_pool(session_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No keywords to re-gate. Run /expand first.",
        )
    if not store.try_mark_running(session_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A run is already in progress for this session.",
        )
    s = get_settings()
    seed_terms, peer_terms = _resolve_peer_terms(session, body)
    threshold = (
        body.relevance_threshold
        if body.relevance_threshold is not None
        else s.relevance_threshold
    )
    edge = (
        body.clustering_edge_threshold
        if body.clustering_edge_threshold is not None
        else s.clustering_edge_threshold
    )
    resolution = (
        body.clustering_resolution
        if body.clustering_resolution is not None
        else s.clustering_resolution
    )
    cap = (
        body.active_per_silo_cap
        if body.active_per_silo_cap is not None
        else s.active_per_silo_cap
    )
    jobs.submit_regate(session_id, threshold, edge, resolution, cap, seed_terms, peer_terms)
    return {
        "status": "running",
        "session_id": session_id,
        "relevance_threshold": threshold,
        "clustering_edge_threshold": edge,
        "clustering_resolution": resolution,
        "active_per_silo_cap": cap,
        "peer_entities": peer_terms,
    }


@router.post("/sessions/{session_id}/fanout", status_code=status.HTTP_202_ACCEPTED)
def fanout_session(
    session_id: str,
    body: FanoutBody,
    response: Response,
    user: AuthedUser = Depends(require_owner),
) -> dict:
    """Recursive Fanout (PRD §7.7, Phase 1). Re-expands each silo's top cluster
    representatives as sub-anchors, then re-gates + re-clusters the enlarged pool.
    Requires a prior /expand (it reads the first pass's clustering log for the
    sub-anchors). Because RF costs 5x-8x a base run, an unconfirmed call returns
    the cost estimate + sub-anchor plan and does NOT spend; set
    `confirm_cost: true` to start. Runs in the background — poll GET /summary.
    Owner-only: for VAs, recursive fanout is always gated behind the approval
    workflow (PRD §11.2 / §11.3), which lands in M9; until then it's owner-direct."""
    session = _require_session(user, session_id)
    _assert_embedding_current(session)
    bind_session_id(session_id)
    clustering_log = session.get("statistical_clustering_log") or {}
    topics = store.list_topics(session_id)
    topic_ids = [t["id"] for t in topics]
    sub_anchors = derive_sub_anchors(
        clustering_log=clustering_log,
        topic_ids=topic_ids,
        per_silo=get_settings().fanout_subanchors_per_silo,
    )
    total = count_sub_anchors(sub_anchors)
    if total == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No sub-anchors to fan out. Run /expand first so the silos have "
            "statistical groupings to deepen.",
        )

    s = get_settings()
    estimate = {
        "sub_anchors_total": total,
        "sub_anchors_per_silo": {
            t["name"]: len(sub_anchors.get(t["id"], [])) for t in topics
        },
        "cost_multiplier_range": [s.fanout_cost_multiplier_low, s.fanout_cost_multiplier_high],
        "note": "Recursive Fanout costs roughly 5x-8x a base run (PRD §7.7). "
        "Re-send with confirm_cost=true to start.",
    }
    if not body.confirm_cost:
        # Nothing was queued — this is a read-only cost preview, not an accepted
        # run, so override the route's default 202.
        response.status_code = status.HTTP_200_OK
        return {"status": "estimate", "session_id": session_id, "estimate": estimate}

    if not store.try_mark_running(session_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A run is already in progress for this session.",
        )
    seed_terms, peer_terms = _resolve_peer_terms(session, body)
    threshold = (
        body.relevance_threshold
        if body.relevance_threshold is not None
        else s.relevance_threshold
    )
    edge = (
        body.clustering_edge_threshold
        if body.clustering_edge_threshold is not None
        else s.clustering_edge_threshold
    )
    resolution = (
        body.clustering_resolution
        if body.clustering_resolution is not None
        else s.clustering_resolution
    )
    cap = (
        body.active_per_silo_cap
        if body.active_per_silo_cap is not None
        else s.active_per_silo_cap
    )
    jobs.submit_fanout(session_id, threshold, edge, resolution, cap, seed_terms, peer_terms)
    return {"status": "running", "session_id": session_id, "estimate": estimate}


@router.post("/sessions/{session_id}/routing-diagnostic")
def routing_diagnostic_endpoint(
    session_id: str, body: RoutingDiagnosticBody, user: AuthedUser = Depends(require_owner)
) -> dict:
    """Read-only: compare candidate silo-anchor strategies by routing probe
    keywords (and the active pool) to their argmax-cosine silo. Used to pick the
    keyword->silo routing signal empirically. No persistence, no status change."""
    _require_session(user, session_id)
    bind_session_id(session_id)
    session = store.get_session(session_id) or {}
    topics = store.list_topics(session_id)
    if not topics:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No silos.")
    active_by_topic = {
        t["id"]: [k["keyword"] for k in store.list_keywords(
            session_id, topic_id=t["id"], status="active", limit=body.active_sample_per_topic)]
        for t in topics
    }
    return routing_diagnostic(
        seed=session.get("seed_keyword", ""),
        topics=[(t["id"], t["name"]) for t in topics],
        rationale_embeddings=store.get_topic_embeddings(session_id),
        active_by_topic=active_by_topic,
        probes=body.probes,
        embed_fn=get_llm().embed,
    )


@router.post("/sessions/{session_id}/lever3-simulate")
def lever3_simulate_endpoint(
    session_id: str, body: RegateBody, user: AuthedUser = Depends(require_owner)
) -> dict:
    """Read-only Lever-3 dry run: argmax-route every active keyword to its best
    silo (raw rationale-anchor cosine) and cluster each silo's reassigned set,
    reporting per-silo grouping counts. Measures the Lever-3 outcome before
    building it. No persistence, no status change."""
    session = _require_session(user, session_id)
    bind_session_id(session_id)
    pool = store.list_all_keyword_pool(session_id)
    if not pool:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="No keywords. Run /expand first.")
    s = get_settings()
    topics = store.list_topics(session_id)
    seed_terms, peer_terms = _resolve_peer_terms(session, body)
    return simulate_best_silo_clustering(
        per_topic_lists=pool,
        topic_names={t["id"]: t["name"] for t in topics},
        topic_embeddings=store.get_topic_embeddings(session_id),
        embed_fn=get_llm().embed,
        relevance_threshold=(body.relevance_threshold
                             if body.relevance_threshold is not None else s.relevance_threshold),
        edge_threshold=(body.clustering_edge_threshold
                        if body.clustering_edge_threshold is not None else s.clustering_edge_threshold),
        resolution=(body.clustering_resolution
                    if body.clustering_resolution is not None else s.clustering_resolution),
        clustering_max_nodes=s.clustering_max_nodes,
        seed_terms=seed_terms,
        peer_terms=peer_terms,
        language_filter=jobs._maybe_language_filter(),
    )


@router.post("/sessions/{session_id}/cluster-preview")
def cluster_preview_endpoint(
    session_id: str, body: ClusterPreviewBody, user: AuthedUser = Depends(require_owner)
) -> dict:
    """Granularity sweep (read-only): embed + gate the stored keyword pool once,
    then report cluster-size stats for each (edge_threshold, resolution) config.
    Synchronous (no persistence, no status change) — it's a quick analysis call
    used to pick clustering settings before committing a /regate."""
    session = _require_session(user, session_id)
    bind_session_id(session_id)
    pool = store.list_all_keyword_pool(session_id)
    if not pool:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No keywords to preview. Run /expand first.",
        )
    s = get_settings()
    threshold = (
        body.relevance_threshold
        if body.relevance_threshold is not None
        else s.relevance_threshold
    )
    topics = store.list_topics(session_id)
    seed_terms, peer_terms = _resolve_peer_terms(session, body)
    return cluster_preview(
        per_topic_lists=pool,
        topic_names={t["id"]: t["name"] for t in topics},
        topic_embeddings=store.get_topic_embeddings(session_id),
        embed_fn=get_llm().embed,
        relevance_threshold=threshold,
        configs=[(float(e), float(r)) for e, r in body.configs],
        relevance_embed_batch=s.relevance_embed_batch,
        clustering_max_nodes=s.clustering_max_nodes,
        seed_terms=seed_terms,
        peer_terms=peer_terms,
        language_filter=jobs._maybe_language_filter(),
    )


class PlanArticlesBody(BaseModel):
    # direct=True skips the LLM orchestrator: every grouping (incl. singletons)
    # becomes an article, then cross-topic dedup collapses duplicates.
    direct: bool = False


# ---- M7b editing bodies (PRD §9.1 / §9.2 / §9.4) --------------------------
_INTENT_RE = "^(informational|commercial|transactional|comparison|navigational)$"


class ClusterEditBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=300)
    intent: str | None = Field(default=None, pattern=_INTENT_RE)
    # H2 outlines are owned by the writer module — not editable here (2026-06-09).


class PromotePrimaryBody(BaseModel):
    keyword_id: str = Field(min_length=1)


class MergeClustersBody(BaseModel):
    survivor_id: str = Field(min_length=1)
    merged_ids: list[str] = Field(min_length=1)
    name: str | None = Field(default=None, min_length=1, max_length=300)


class SplitClusterBody(BaseModel):
    keyword_ids: list[str] = Field(min_length=1)
    name: str = Field(min_length=1, max_length=300)
    primary_keyword_id: str | None = None


class KeywordStatusBody(BaseModel):
    keyword_ids: list[str] = Field(min_length=1)
    status: str = Field(pattern="^(active|excluded|covered)$")


class KeywordMoveBody(BaseModel):
    keyword_ids: list[str] = Field(min_length=1)
    cluster_id: str | None = None  # None -> Unassigned bucket


class SessionPatchBody(BaseModel):
    project_id: str | None = None
    archived: bool | None = None


@router.post("/sessions/{session_id}/plan-articles", status_code=status.HTTP_202_ACCEPTED)
def plan_articles(
    session_id: str,
    user: AuthedUser = Depends(require_user),
    body: PlanArticlesBody | None = None,
) -> dict:
    """Kick off M5 article planning (§7.10) in the background: SERP for candidate
    primaries -> per-silo orchestrator -> cross-topic dedup -> persist clusters +
    coverage gaps. With body {"direct": true}, skips the orchestrator (groupings
    -> articles directly). Returns immediately; poll GET /summary for status."""
    session = _require_session(user, session_id)
    _assert_embedding_current(session)
    bind_session_id(session_id)
    if not (session.get("statistical_clustering_log") or {}).get("topics"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No statistical clustering to plan from. Run /expand first.",
        )
    if not store.try_mark_running(session_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A run is already in progress for this session.",
        )
    jobs.submit_plan(session_id, direct=bool(body and body.direct))
    return {"status": "running", "session_id": session_id, "direct": bool(body and body.direct)}


@router.get("/sessions/{session_id}/clusters")
def get_clusters(session_id: str, user: AuthedUser = Depends(require_user)) -> dict:
    """Read-only article plan + coverage gaps for a session."""
    _require_session(user, session_id)
    return {
        "clusters": store.list_clusters(session_id),
        "coverage_gaps": store.list_coverage_gaps(session_id),
    }


# ---- M7b cluster editing (PRD §9.2) ---------------------------------------
@router.patch("/clusters/{cluster_id}")
def edit_cluster(
    cluster_id: str, body: ClusterEditBody, user: AuthedUser = Depends(require_user)
) -> dict:
    """Rename an article or change its intent (§9.2). VAs may only rename — intent
    is owner-only (§10.2: VA cluster actions are limited to Rename + Move keyword
    in/out). H2 outlines are not editable here — the writer module owns them."""
    _require_cluster(user, cluster_id)
    if body.intent is not None and get_role(user) != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="VA mode can only rename an article, not edit its intent.",
        )
    fields: dict = {}
    if body.name is not None:
        fields["name"] = body.name.strip()
    if body.intent is not None:
        fields["intent"] = body.intent
    if not fields:
        return store.get_cluster(cluster_id)
    return store.update_cluster(cluster_id, fields)


@router.post("/clusters/{cluster_id}/promote-primary")
def promote_primary(
    cluster_id: str, body: PromotePrimaryBody, user: AuthedUser = Depends(require_owner)
) -> dict:
    """Make a supporting keyword the article's primary; the old primary demotes
    to supporting (§9.2). Owner-only (§10.2: not in the VA cluster-action set)."""
    _require_cluster(user, cluster_id)
    try:
        return store.promote_primary(cluster_id, body.keyword_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/clusters/{cluster_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cluster(cluster_id: str, user: AuthedUser = Depends(require_owner)) -> None:
    """Delete an article; its keywords drop to the topic's Unassigned bucket — they
    are never destroyed (§9.2). Owner-only (§11.2); VAs request restructure instead."""
    _require_cluster(user, cluster_id)
    store.delete_cluster(cluster_id)


@router.post("/clusters/merge")
def merge_clusters(
    body: MergeClustersBody, user: AuthedUser = Depends(require_owner)
) -> dict:
    """Merge two or more articles into one (§9.2). All must belong to one session
    the caller owns. Owner-only (§11.2)."""
    _, survivor_sid = _require_cluster(user, body.survivor_id)
    for cid in body.merged_ids:
        _, sid = _require_cluster(user, cid)
        if sid != survivor_sid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="All merged articles must belong to the same session.",
            )
    return store.merge_clusters(survivor_sid, body.survivor_id, body.merged_ids, name=body.name)


@router.post("/clusters/{cluster_id}/split")
def split_cluster(
    cluster_id: str, body: SplitClusterBody, user: AuthedUser = Depends(require_owner)
) -> dict:
    """Split a subset of an article's keywords into a new article (§9.2, manual
    selection). Returns the new article. Owner-only (§11.2)."""
    _require_cluster(user, cluster_id)
    try:
        return store.split_cluster(
            cluster_id, body.keyword_ids, body.name.strip(), body.primary_keyword_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


# ---- M7b keyword bulk actions (PRD §9.1) ----------------------------------
@router.post("/sessions/{session_id}/keywords/status")
def bulk_keyword_status(
    session_id: str, body: KeywordStatusBody, user: AuthedUser = Depends(require_user)
) -> dict:
    """Bulk exclude / mark-covered / restore-to-active for selected keywords (§9.1).
    Scoped to the session, so only its keywords are affected. VAs may not Exclude
    (§9 / §10.2: the VA bulk menu is Move-to-cluster + Mark-covered only)."""
    _require_session(user, session_id)
    if body.status == "excluded" and get_role(user) != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="VA mode cannot exclude keywords.",
        )
    updated = store.set_keywords_status(session_id, body.keyword_ids, body.status)
    return {"updated": updated}


@router.post("/sessions/{session_id}/keywords/move")
def bulk_keyword_move(
    session_id: str, body: KeywordMoveBody, user: AuthedUser = Depends(require_user)
) -> dict:
    """Move selected keywords to another article, or to Unassigned (cluster_id
    null) (§9.1 / §9.2)."""
    _require_session(user, session_id)
    if body.cluster_id is not None:
        _, sid = _require_cluster(user, body.cluster_id)
        if sid != session_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Target article belongs to a different session.",
            )
    updated = store.move_keywords(session_id, body.keyword_ids, body.cluster_id)
    return {"updated": updated}


# ---- M7b coverage-gap decisions (PRD §9.2) --------------------------------
@router.post("/coverage-gaps/{gap_id}/accept")
def accept_gap(gap_id: str, user: AuthedUser = Depends(require_owner)) -> dict:
    """Accept a flagged gap -> create an empty placeholder article for it (§9.2).
    Owner-only: accepting/dismissing changes the article set, which is an editorial
    (restructure) decision VAs route to the owner (§10.2)."""
    _require_gap(user, gap_id)
    return store.accept_gap(gap_id)


@router.post("/coverage-gaps/{gap_id}/dismiss", status_code=status.HTTP_204_NO_CONTENT)
def dismiss_gap(gap_id: str, user: AuthedUser = Depends(require_owner)) -> None:
    """Dismiss a flagged gap (§9.2). Owner-only, like accept."""
    _require_gap(user, gap_id)
    store.dismiss_gap(gap_id)


# ---- M6 site architecture (PRD §7.11) -------------------------------------
@router.post("/sessions/{session_id}/architecture", status_code=status.HTTP_202_ACCEPTED)
def generate_architecture(
    session_id: str, user: AuthedUser = Depends(require_owner)
) -> dict:
    """Kick off M6 site architecture generation (§7.11) in the background: one
    pillar per article-bearing silo (editorial fields via Opus) + the internal
    linking matrix, persisted to site_architecture. Requires a prior
    /plan-articles (it organizes the existing clusters, never re-plans). Idempotent
    — re-running regenerates (PRD §9.3). Returns immediately; poll GET /summary for
    status, then GET /architecture for the result. Owner-only: VAs get a read-only
    architecture view and cannot (re)generate it (PRD §11.2 / §10.3)."""
    session = _require_session(user, session_id)
    _assert_embedding_current(session)
    bind_session_id(session_id)
    if not store.list_clusters(session_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No article plan to build an architecture from. "
            "Run /plan-articles first.",
        )
    if not store.try_mark_running(session_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A run is already in progress for this session.",
        )
    jobs.submit_architecture(session_id)
    return {"status": "running", "session_id": session_id}


@router.get("/sessions/{session_id}/architecture")
def get_architecture(session_id: str, user: AuthedUser = Depends(require_user)) -> dict:
    """Read-only site architecture for a session (the M6 API view; the two-panel
    Architecture View UI is M7). 404 until /architecture has produced one."""
    _require_session(user, session_id)
    arch = store.get_architecture(session_id)
    if not arch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No architecture generated yet. Run POST /architecture first.",
        )
    return arch


@router.get("/sessions/{session_id}/keywords")
def get_keywords(
    session_id: str,
    user: AuthedUser = Depends(require_user),
    topic_id: str | None = None,
    status: str | None = None,
    statuses: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[dict]:
    """Keywords for a session. `statuses` (comma-separated) takes precedence over
    `status` — the Table/Cluster views pass `active,excluded,covered` to fetch
    only surviving keywords (PRD §9.1)."""
    _require_session(user, session_id)
    status_list = (
        [s for s in (statuses.split(",") if statuses else []) if s] or None
    )
    return store.list_keywords(
        session_id,
        topic_id=topic_id,
        status=status,
        statuses=status_list,
        limit=min(limit, 500),
        offset=offset,
    )


@router.get("/sessions/{session_id}/cluster-keywords")
def get_cluster_keywords(
    session_id: str,
    user: AuthedUser = Depends(require_user),
) -> list[dict]:
    """Surviving keywords for the Cluster View (§9.2), tagged with within-cluster
    deduplication so the card shows one variant per intent instead of every
    phrasing the gate kept. Returns the full set in one shot (no pagination —
    the Cluster View needs them all to group by cluster_id), each row carrying
    a `dedupe_canonical_id` field (null when the row IS the canonical, else the
    id of the variant that should be shown in its place). The Table View / CSV
    exports keep using `/keywords`; they intentionally show every variant."""
    from fanout import cluster_dedupe

    _require_session(user, session_id)
    rows = store.list_clustered_keywords_with_embeddings(session_id)
    inputs = [
        cluster_dedupe.KeywordRow(
            id=r["id"],
            cluster_id=r["cluster_id"],
            keyword=r["keyword"],
            volume=r.get("volume"),
            relevance_score=r.get("relevance_score"),
            is_primary_for_cluster=bool(r.get("is_primary_for_cluster")),
            embedding=r.get("embedding"),
        )
        for r in rows
    ]
    settings = get_settings()
    mapping = cluster_dedupe.dedupe_by_cluster(
        inputs,
        cosine_threshold=settings.cluster_display_dedupe_cosine_threshold,
    )
    # Strip the embedding before returning — it never leaves the backend.
    out: list[dict] = []
    for r in rows:
        row = {k: v for k, v in r.items() if k != "embedding"}
        canonical = mapping.get(row["id"])
        row["dedupe_canonical_id"] = canonical if canonical and canonical != row["id"] else None
        out.append(row)
    return out


# ---- Session browser (PRD §9.4) -------------------------------------------
@router.get("/projects/{project_id}/sessions")
def list_project_sessions(
    project_id: str,
    user: AuthedUser = Depends(require_user),
    include_archived: bool = False,
) -> list[dict]:
    """Sessions under a project, newest first, for the Session Browser (§9.4).
    Each carries seed, status, coverage mode, cluster count, and timestamps so the
    UI can resume a session. RLS-scoped to what the caller may see. Archived
    sessions are hidden unless include_archived=true."""
    if not store.project_visible_to_user(user.access_token, project_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        )
    return store.list_sessions(user.access_token, project_id, include_archived=include_archived)


@router.get("/sessions")
def list_all_sessions(
    user: AuthedUser = Depends(require_user),
    include_archived: bool = False,
) -> list[dict]:
    """All sessions the caller may see (owner overview), newest first — no project
    or client filter. Backs the project-free session browser when the Fanout UI is
    not client-scoped. RLS-scoped; archived hidden unless include_archived=true."""
    return store.list_all_sessions(
        user.access_token, include_archived=include_archived
    )


@router.get("/clients/{client_id}/sessions")
def list_client_sessions(
    client_id: str,
    user: AuthedUser = Depends(require_user),
    include_archived: bool = False,
) -> list[dict]:
    """Runs belonging to an AR Tools client (client-scoped runs view), newest
    first. Same row shape as the project browser. RLS-scoped to the runs the
    caller may see; archived hidden unless include_archived=true. Backs the
    Fanout UI when it is opened from a client's Content Scheduler card."""
    return store.list_client_sessions(
        user.access_token, client_id, include_archived=include_archived
    )


# ---- Pre-publish ranking check (per client) -------------------------------
class PrepublishActionBody(BaseModel):
    cluster_ids: list[str] = Field(default_factory=list)
    # 'skip' / 'refresh' to set, null to clear the decision.
    action: str | None = Field(default=None, pattern="^(skip|refresh)$")


@router.post(
    "/sessions/{session_id}/ranking-check", status_code=status.HTTP_202_ACCEPTED
)
def run_ranking_check(
    session_id: str, user: AuthedUser = Depends(require_user)
) -> dict:
    """Kick off the per-client pre-publish ranking check in the background: does
    the client already rank top-10 for each planned article's target keyword
    (GSC first, DataForSEO SERP for the residue)? Result lands on
    `/summary`.prepublish_rank_check. Returns immediately (202)."""
    _require_session(user, session_id)
    bind_session_id(session_id)
    jobs.submit_prepublish_rank_check(session_id)
    return {"status": "running", "session_id": session_id}


@router.post("/sessions/{session_id}/prepublish-action")
def set_prepublish_action(
    session_id: str, body: PrepublishActionBody, user: AuthedUser = Depends(require_user)
) -> dict:
    """Record the user's decision for already-ranking articles before they accept
    the content map: skip them, or refresh the existing page instead of writing a
    new article (or null to clear). Scoped to the session's own clusters."""
    _require_session(user, session_id)
    updated = store.set_clusters_prepublish_action(
        session_id, body.cluster_ids, body.action
    )
    return {"updated": updated, "action": body.action}


@router.patch("/sessions/{session_id}")
def patch_session(
    session_id: str, body: SessionPatchBody, user: AuthedUser = Depends(require_user)
) -> dict:
    """Session-browser mutations (§9.4): archive/unarchive, or move to another
    project the caller owns."""
    _require_session(user, session_id)
    if body.project_id is not None:
        if not store.project_visible_to_user(user.access_token, body.project_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Target project not found"
            )
        store.move_session(session_id, body.project_id)
    if body.archived is not None:
        store.set_session_archived(session_id, body.archived)
    return {"session_id": session_id, "moved": body.project_id is not None,
            "archived": body.archived}


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(session_id: str, user: AuthedUser = Depends(require_owner)) -> None:
    """Permanently delete a session and all its data (§9.4). Irreversible.
    Owner-only (§11.2: VAs cannot delete sessions)."""
    _require_session(user, session_id)
    store.delete_session(session_id)


# ---- Topic review actions (PRD §7.1.4) ------------------------------------
@router.post("/sessions/{session_id}/topics")
def add_topic(
    session_id: str, body: AddTopicBody, user: AuthedUser = Depends(require_user)
) -> dict:
    _require_session(user, session_id)
    bind_session_id(session_id)
    return store.insert_custom_topic(
        session_id,
        name=body.name.strip(),
        rationale=body.rationale,
        relationship_type=body.relationship_type.value,
        is_broader_class=body.is_broader_class
        or body.relationship_type is RelationshipType.broader_class,
    )


@router.patch("/topics/{topic_id}")
def edit_topic(
    topic_id: str, body: EditTopicBody, user: AuthedUser = Depends(require_user)
) -> dict:
    topic = store.get_topic(topic_id)
    if not topic:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topic not found")
    _require_session(user, topic["session_id"])
    bind_session_id(topic["session_id"])

    fields: dict = {}
    if body.name is not None:
        fields["name"] = body.name.strip()
    if body.rationale is not None:
        fields["rationale"] = body.rationale
    if body.relationship_type is not None:
        fields["relationship_type"] = body.relationship_type.value
        fields["is_broader_class"] = body.relationship_type is RelationshipType.broader_class
    if not fields:
        return topic

    # An edited LLM silo is retagged so provenance is traceable (PRD §13).
    if topic["source"] == "llm_proposed":
        fields["source"] = "llm_proposed_then_user_edited"
    return store.update_topic(topic_id, fields)


@router.delete("/topics/{topic_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_topic(topic_id: str, user: AuthedUser = Depends(require_user)) -> None:
    topic = store.get_topic(topic_id)
    if not topic:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topic not found")
    _require_session(user, topic["session_id"])
    bind_session_id(topic["session_id"])
    store.delete_topic(topic_id)


@router.get("/debug/embedding-health")
def embedding_health(user: AuthedUser = Depends(require_owner)) -> dict:
    """Owner-only: probe the Gemini embedding backend with a one-string call so the
    `GEMINI_API_KEY` + API + 1536-dim access can be verified on the deployed stack
    BEFORE flipping `EMBEDDING_PROVIDER` to gemini. Builds the Gemini backend
    directly from settings — it does NOT change the active provider, touch any
    session, or read stored vectors. Returns `ok` + the returned dimension + L2
    norm + latency, or the failure reason (the key is sent as a header, so it
    never appears in the error string)."""
    import math
    import time as _t

    from fanout.config import get_settings
    from fanout.llm.embeddings import GeminiEmbedder

    s = get_settings()
    out: dict = {
        "active_embedding_provider": s.embedding_provider,
        "gemini_model": s.gemini_embedding_model,
        "expected_dim": s.gemini_embedding_dim,
        "gemini_api_key_present": bool(s.gemini_api_key),
    }
    try:
        embedder = GeminiEmbedder(
            api_key=s.gemini_api_key,
            model=s.gemini_embedding_model,
            output_dim=s.gemini_embedding_dim,
            task_type=s.gemini_embedding_task_type,
        )
        started = _t.perf_counter()
        vec = embedder.embed(["embedding health check"])[0]
        out.update(
            {
                "ok": True,
                "returned_dim": len(vec),
                "dim_matches": len(vec) == s.gemini_embedding_dim,
                "l2_norm": round(math.sqrt(sum(x * x for x in vec)), 4),
                "latency_ms": round((_t.perf_counter() - started) * 1000, 1),
            }
        )
    except Exception as exc:  # noqa: BLE001 — report the failure to the owner
        out.update({"ok": False, "error": str(exc)})
    return out


# Re-export for callers that validate relationship types.
__all__ = ["router", "PROPOSABLE_TYPES"]


# ----- M12 SIE Term & Entity analysis (owner-only validation surface) --------
class TermAnalysisBody(BaseModel):
    force_refresh: bool = False
    outlier_mode: str = Field(default="safe", pattern="^(safe|aggressive)$")


def _cluster_keyword_and_location(
    user: AuthedUser, session_id: str, cluster_id: str
) -> tuple[str, int, str]:
    """(primary keyword text, session location_code, session_id) for a cluster the
    caller can see. The SIE keyword is the cluster's primary keyword (the article's
    target keyword)."""
    cluster, sid = _require_cluster(user, cluster_id)
    if sid != session_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cluster not found")
    session = _require_session(user, sid)
    pkid = cluster.get("primary_keyword_id")
    if not pkid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cluster has no primary keyword to analyze",
        )
    keyword = store.get_keyword_texts([pkid]).get(pkid)
    if not keyword:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Cluster primary keyword not found"
        )
    return keyword, store.session_location_code(session), sid


@router.post("/sessions/{session_id}/clusters/{cluster_id}/term-analysis")
def start_term_analysis(
    session_id: str, cluster_id: str, response: Response,
    body: TermAnalysisBody | None = None, user: AuthedUser = Depends(require_owner),
) -> dict:
    """Owner-only (M12 validation surface). Cache hit -> 200 + stored report; miss
    -> 202 + the SIE job is submitted (poll GET until present)."""
    from fanout.sie import cache as sie_cache

    body = body or TermAnalysisBody()
    keyword, location_code, sid = _cluster_keyword_and_location(user, session_id, cluster_id)
    if not body.force_refresh:
        row = sie_cache.get_fresh_analysis(keyword, location_code)
        if row:
            return {"status": "complete", "keyword": keyword, "report": row["output_json"]}
    jobs.submit_sie(
        sid, cluster_id, keyword, location_code,
        outlier_mode=body.outlier_mode, force_refresh=body.force_refresh,
    )
    response.status_code = status.HTTP_202_ACCEPTED
    return {"status": "running", "keyword": keyword}


@router.get("/sessions/{session_id}/clusters/{cluster_id}/term-analysis")
def get_term_analysis(
    session_id: str, cluster_id: str, user: AuthedUser = Depends(require_owner)
) -> dict:
    """The cached SIE report for a cluster's keyword (404 until analyzed)."""
    from fanout.sie import cache as sie_cache

    keyword, location_code, _sid = _cluster_keyword_and_location(user, session_id, cluster_id)
    row = sie_cache.get_fresh_analysis(keyword, location_code)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No analysis yet")
    return {"status": "complete", "keyword": keyword, "report": row["output_json"]}


# ----- M13 Brief Generator (answer-engine-first; owner-only validation surface) ----
class BriefBody(BaseModel):
    force_refresh: bool = False


@router.post("/sessions/{session_id}/clusters/{cluster_id}/brief")
def start_brief(
    session_id: str, cluster_id: str, response: Response,
    body: BriefBody | None = None, user: AuthedUser = Depends(require_owner),
) -> dict:
    """Owner-only (M13 validation surface). Generate the content brief (Writer Input A)
    for a cluster's primary keyword. Cache hit -> 200 + stored brief; miss -> 202 + the
    brief job is submitted (poll GET until present). Runs lazily at write time only."""
    from fanout.briefgen import cache as brief_cache

    body = body or BriefBody()
    keyword, location_code, sid = _cluster_keyword_and_location(user, session_id, cluster_id)
    if not body.force_refresh:
        row = brief_cache.get_fresh_brief(keyword, location_code)
        if row:
            return {"status": "complete", "keyword": keyword, "brief": row["output_json"]}
    jobs.submit_brief(sid, cluster_id, keyword, location_code, force_refresh=body.force_refresh)
    response.status_code = status.HTTP_202_ACCEPTED
    return {"status": "running", "keyword": keyword}


@router.get("/sessions/{session_id}/clusters/{cluster_id}/brief")
def get_brief(
    session_id: str, cluster_id: str, user: AuthedUser = Depends(require_owner)
) -> dict:
    """The cached content brief for a cluster's keyword (404 until generated)."""
    from fanout.briefgen import cache as brief_cache

    keyword, location_code, _sid = _cluster_keyword_and_location(user, session_id, cluster_id)
    row = brief_cache.get_fresh_brief(keyword, location_code)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No brief yet")
    return {"status": "complete", "keyword": keyword, "brief": row["output_json"]}


# ----- M14 Content Writer (article generation; owner-only) ------------------
class GenerateArticleBody(BaseModel):
    force_refresh: bool = False


@router.post("/sessions/{session_id}/clusters/{cluster_id}/generate-article")
def start_article(
    session_id: str, cluster_id: str, response: Response,
    body: GenerateArticleBody | None = None, user: AuthedUser = Depends(require_owner),
) -> dict:
    """Owner-only. Generate the full article for a cluster (ensures Brief + SIE as stage
    1, then writes). Existing article + no force_refresh -> 200 + it; in-flight -> 409;
    else 202 + the job is submitted (poll GET). Runs lazily at write time only."""
    from fanout.writer import store as article_store

    body = body or GenerateArticleBody()
    keyword, location_code, sid = _cluster_keyword_and_location(user, session_id, cluster_id)
    if jobs.article_inflight(cluster_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Article already generating")
    if not body.force_refresh:
        row = article_store.get_latest_article(cluster_id)
        if row:
            return {"status": "complete", "keyword": keyword, "article": row["article_json"]}
    if not jobs.submit_article(sid, cluster_id, keyword, location_code, force_refresh=body.force_refresh):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Article already generating")
    response.status_code = status.HTTP_202_ACCEPTED
    return {"status": "running", "keyword": keyword}


class BulkGenerateBody(BaseModel):
    cluster_ids: list[str]


@router.post("/sessions/{session_id}/generate-articles")
def start_articles(
    session_id: str, body: BulkGenerateBody, user: AuthedUser = Depends(require_owner),
) -> dict:
    """Owner-only bulk generate: submit an article job for each cluster_id (skipping any
    that already have a fresh article, are in-flight, or aren't visible). Jobs queue on the
    bounded worker pool, so 'all at once' drains a few at a time — not N parallel calls."""
    from fanout.writer import store as article_store

    submitted: list[str] = []
    skipped: list[str] = []
    for cid in (body.cluster_ids or [])[:500]:
        try:
            keyword, location_code, sid = _cluster_keyword_and_location(user, session_id, cid)
        except HTTPException:
            skipped.append(cid)
            continue
        if article_store.get_latest_article(cid) or not jobs.submit_article(
            sid, cid, keyword, location_code
        ):
            skipped.append(cid)
            continue
        submitted.append(cid)
    return {"submitted": submitted, "skipped": skipped, "count": len(submitted)}


@router.get("/sessions/{session_id}/articles")
def list_articles(
    session_id: str, user: AuthedUser = Depends(require_owner)
) -> dict:
    """The Articles library: the latest generated article per cluster for a session (metadata
    only — name, words, cost, date), newest first. The reader fetches a body one at a time via
    the per-cluster article endpoint."""
    from fanout.writer import store as article_store

    _require_session(user, session_id)
    rows = article_store.list_session_articles(session_id)
    names = {c["id"]: c["name"] for c in store.list_clusters(session_id)}
    items = [{
        "cluster_id": r["cluster_id"],
        "name": names.get(r["cluster_id"], "—"),
        "total_word_count": r.get("total_word_count"),
        "cost_usd": r.get("cost_usd"),
        "generated_at": r.get("generated_at"),
        "scheduled": r.get("scheduled_article_run_id") is not None,
    } for r in rows]
    items.sort(key=lambda x: x["generated_at"] or "", reverse=True)
    return {"articles": items, "count": len(items)}


@router.post("/sessions/{session_id}/articles/download-all")
def download_all_articles(
    session_id: str, user: AuthedUser = Depends(require_owner)
) -> dict:
    """Bundle every written article (latest per cluster) as a .zip of Markdown files, freeze it
    to the private bucket, and return a short-lived signed URL — same infra as CSV export."""
    import uuid as _uuid

    from fanout.csv_export import snapshot_timestamp, zip_named_csvs
    from fanout.storage import exports as export_store
    from fanout.writer import store as article_store
    from fanout.writer.slugs import slugify

    _require_session(user, session_id)
    bodies = article_store.get_session_article_markdown(session_id)
    if not bodies:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No articles to download yet")

    names = {c["id"]: c["name"] for c in store.list_clusters(session_id)}
    used: set[str] = set()
    named: list[tuple[str, str]] = []
    for cluster_id, markdown in bodies:
        base = slugify(names.get(cluster_id, cluster_id))
        fn = f"{base}.md"
        i = 2
        while fn in used:
            fn = f"{base}-{i}.md"
            i += 1
        used.add(fn)
        named.append((fn, markdown))

    data = zip_named_csvs(named)        # generic (filename, text) -> zip
    object_path = f"{user.id}/{session_id}/articles-{snapshot_timestamp()}-{_uuid.uuid4().hex[:8]}.zip"
    export_store.upload_snapshot(object_path, data, "application/zip")
    download_url = export_store.create_signed_url(
        object_path, get_settings().csv_signed_url_ttl_s, download_name=f"articles-{session_id[:8]}.zip",
    )
    return {"download_url": download_url, "count": len(named)}


class PublishConfigBody(BaseModel):
    github_repo: str | None = None          # "owner/repo"
    github_branch: str | None = None
    github_content_path: str | None = None  # e.g. "src/content/blog"
    drive_folder_id: str | None = None      # optional Google Drive folder


@router.patch("/sessions/{session_id}/publish-config")
def set_publish_config(
    session_id: str, body: PublishConfigBody, user: AuthedUser = Depends(require_owner)
) -> dict:
    """Set the session's publish targets (GitHub repo/branch/path + Drive folder). Stored in
    `sessions.publish_config`; the tokens themselves are server env vars."""
    session = _require_session(user, session_id)
    cfg = dict(session.get("publish_config") or {})
    gh = dict(cfg.get("github") or {})
    if body.github_repo is not None:
        gh["repo"] = body.github_repo.strip()
    if body.github_branch is not None:
        gh["branch"] = body.github_branch.strip()
    if body.github_content_path is not None:
        gh["content_path"] = body.github_content_path.strip().strip("/")
    cfg["github"] = gh
    if body.drive_folder_id is not None:
        cfg["drive"] = {"folder_id": body.drive_folder_id.strip()}
    store.update_session(session_id, {"publish_config": cfg})
    return {"publish_config": cfg}


@router.post("/sessions/{session_id}/clusters/{cluster_id}/publish/drive")
def publish_cluster_drive(
    session_id: str, cluster_id: str, user: AuthedUser = Depends(require_owner)
) -> dict:
    """Save one article to Google Drive as a Google Doc (from its HTML)."""
    from fanout.writer import store as article_store
    from fanout.writer.publish import drive as drive_pub

    session = _require_session(user, session_id)
    if store.cluster_session_id(cluster_id) != session_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cluster not found")
    row = article_store.get_latest_article(cluster_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No article to save")
    aj = row["article_json"]
    html = aj.get("article_html") or ""
    if not html:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Article has no HTML body")
    folder_id = ((session.get("publish_config") or {}).get("drive") or {}).get("folder_id") or None
    try:
        res = drive_pub.create_doc_from_html(name=aj.get("title") or "Article", html=html, folder_id=folder_id)
    except drive_pub.DrivePublishError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"published": True, **res}


def _github_target(session: dict) -> tuple[str, str, str, str]:
    """(repo, branch, content_path, token) for a session's GitHub target, or a 400 if the repo
    isn't configured / the server has no token."""
    s = get_settings()
    gh = (session.get("publish_config") or {}).get("github") or {}
    repo = (gh.get("repo") or "").strip()
    if not repo:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Set the GitHub repo (owner/repo) for this session first.")
    if not s.github_publish_token:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="GitHub publishing isn't configured on the server (no token).")
    return (repo, gh.get("branch") or s.github_default_branch,
            (gh.get("content_path") or s.github_default_content_path).strip("/"),
            s.github_publish_token)


def _astro_file(content_path: str, *, markdown: str, title: str, article_slug: str, silo_name: str):
    from fanout.writer.publish.markdown import build_astro_markdown
    from fanout.writer.slugs import slugify

    silo_slug = slugify(silo_name) if silo_name else "content"
    md = build_astro_markdown(
        article_markdown=markdown, title=title, slug=article_slug, silo=silo_name)
    return f"{content_path}/{silo_slug}/{article_slug}.md", md


@router.post("/sessions/{session_id}/clusters/{cluster_id}/publish/github")
def publish_cluster_github(
    session_id: str, cluster_id: str, user: AuthedUser = Depends(require_owner)
) -> dict:
    """Commit one article to the session's GitHub repo as Astro content Markdown."""
    from fanout.writer import store as article_store
    from fanout.writer.publish import github as gh_pub

    session = _require_session(user, session_id)
    repo, branch, content_path, token = _github_target(session)
    row = article_store.get_latest_article(cluster_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No article to publish")
    cluster = store.get_cluster(cluster_id)
    if not cluster or store.cluster_session_id(cluster_id) != session_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cluster not found")
    article_slug = store.ensure_session_slugs(session_id).get(cluster_id) or cluster.get("slug")
    if not article_slug:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cluster has no slug")
    topic = store.get_topic(cluster["topic_id"]) or {}
    aj = row["article_json"]
    path, content = _astro_file(
        content_path, markdown=aj.get("article_markdown", ""), title=aj.get("title", ""),
        article_slug=article_slug, silo_name=topic.get("name", ""))
    try:
        res = gh_pub.commit_file(
            repo=repo, path=path, content=content,
            message=f"content: {aj.get('title') or path}", branch=branch, token=token)
    except gh_pub.GitHubPublishError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"published": True, **res}


@router.post("/sessions/{session_id}/publish/github")
def publish_all_github(
    session_id: str, user: AuthedUser = Depends(require_owner)
) -> dict:
    """Commit every written article to the repo in ONE commit (Git Trees API)."""
    from fanout.writer import store as article_store
    from fanout.writer.publish import github as gh_pub

    session = _require_session(user, session_id)
    repo, branch, content_path, token = _github_target(session)
    bodies = dict(article_store.get_session_article_markdown(session_id))   # {cluster_id: md}
    if not bodies:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No articles to publish")
    slugs = store.ensure_session_slugs(session_id)
    topics = {t["id"]: t for t in store.list_topics(session_id)}
    files: list[tuple[str, str]] = []
    for c in store.list_clusters(session_id):
        markdown = bodies.get(c["id"])
        article_slug = slugs.get(c["id"]) or c.get("slug")
        if not markdown or not article_slug:
            continue
        silo_name = (topics.get(c["topic_id"]) or {}).get("name", "")
        files.append(_astro_file(content_path, markdown=markdown, title="",
                                 article_slug=article_slug, silo_name=silo_name))
    if not files:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No publishable articles")
    try:
        res = gh_pub.commit_tree(
            repo=repo, branch=branch, files=files,
            message=f"content: publish {len(files)} articles", token=token)
    except gh_pub.GitHubPublishError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"published": True, **res}


@router.get("/sessions/{session_id}/clusters/{cluster_id}/article")
def get_article(
    session_id: str, cluster_id: str, user: AuthedUser = Depends(require_owner)
) -> dict:
    """The latest generated article for a cluster (404 until generated)."""
    from fanout.writer import store as article_store

    keyword, _location_code, _sid = _cluster_keyword_and_location(user, session_id, cluster_id)
    row = article_store.get_latest_article(cluster_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No article yet")
    return {"status": "complete", "keyword": keyword, "article": row["article_json"]}


@router.post("/sessions/{session_id}/clusters/{cluster_id}/split-uncovered")
def split_uncovered(
    session_id: str, cluster_id: str, user: AuthedUser = Depends(require_owner)
) -> dict:
    """Owner-confirmed (from the article's 'unused keywords' prompt): group this cluster's
    uncovered keywords into new articles and queue them for generation. Recursion-guarded;
    uncapped (owner choice)."""
    keyword, location_code, sid = _cluster_keyword_and_location(user, session_id, cluster_id)
    return jobs.split_uncovered_and_write(sid, cluster_id, keyword, location_code)
