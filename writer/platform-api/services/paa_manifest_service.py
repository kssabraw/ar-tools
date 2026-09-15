"""PAA → SEO Neo Phase 2 — the impure service layer (I/O) for the prep-sheet
MANIFEST (the "seam"; PRD §11).

Orchestrates the manifest flow over reused suite seams:

  * **build / refresh** — resolve the live URLs of the assets v1 already produced
    (a PAA post's ``runs.published_url`` via ``paa_items.run_id``, a GBP post's
    ``gbp_posts.search_url``, syndication copies) → assemble the auto content rows
    (``paa_manifest.build_content_asset_rows``) → on the FIRST build, seed the
    standard authority bundle + the audio/video/influencer checklist rows; a
    rebuild refreshes ONLY the auto rows and never clobbers operator edits
    (``paa_manifest.merge_rows``). Recomputes the cost + QA roll-ups.
  * **cost** — ``paa_manifest.build_cost_summary`` over the reused Recipe-Engine
    catalog (honest "not estimated" for off-menu RD 100).
  * **QA** — the ``paa_manifest_qa`` async job reviews each content asset's LIVE
    URL via the QA Agent's bare-URL path (``qa_service.review_url``), gated on
    ``qa_enabled`` with v1's deterministic per-item checks as the free fallback,
    and rolls the verdicts up onto the manifest.
  * **export / hand-off** — CSV + JSON (deterministic, from the pure renderers)
    + an optional Google Sheet into the client's Drive folder
    (``google_docs.create_google_sheet``).

Guardrail (PRD §9): the suite tracks / costs / QAs / hands off a manifest — it
NEVER executes the authority layer. There is no code path here that runs a link
blast; authority-row status is human-set only.
"""

from __future__ import annotations

import logging
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import paa_manifest

logger = logging.getLogger(__name__)

_CLIENT_COLS = (
    "id, name, website_url, business_location, gbp, drive_folders, "
    "google_drive_folder_id, rank_tracking_location_code"
)

# Human-editable columns on a manifest asset (never category/source/kind — those
# are set at build). cost_task_type is editable so an operator can point an
# authority row at a different priced tactic.
_ASSET_EDITABLE = {"label", "url", "note", "status", "cost_quantity", "cost_task_type", "position"}


def _sb():
    return get_supabase()


def _client(client_id: str) -> dict:
    rows = (
        _sb().table("clients").select(_CLIENT_COLS).eq("id", client_id).limit(1).execute()
    ).data or []
    if not rows:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="client_not_found")
    return rows[0]


def _set(set_id: str) -> dict:
    rows = _sb().table("paa_sets").select("*").eq("id", set_id).limit(1).execute().data or []
    if not rows:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="paa_set_not_found")
    return rows[0]


def _items(set_id: str) -> list[dict]:
    return (
        _sb().table("paa_items").select("*").eq("set_id", set_id)
        .eq("chosen", True).order("position").execute()
    ).data or []


# ── resolve the live links v1 already produced ────────────────────────────────


def _resolve_content_links(set_row: dict, items: list[dict]) -> list[dict]:
    """For each chosen PAA item, resolve its live PAA-post URL (runs), GBP-post
    URL (gbp_posts), and syndication copies. Returns the shape
    ``paa_manifest.build_content_asset_rows`` expects. Best-effort per source."""
    run_ids = [i["run_id"] for i in items if i.get("run_id")]
    gbp_ids = [i["gbp_post_id"] for i in items if i.get("gbp_post_id")]

    runs: dict[str, dict] = {}
    if run_ids:
        try:
            for r in (
                _sb().table("runs").select("id, published_url")
                .in_("id", run_ids).execute()
            ).data or []:
                runs[r["id"]] = r
        except Exception as exc:  # pragma: no cover - best-effort
            logger.warning("paa_manifest.runs_read_failed", extra={"error": str(exc)})

    gbp: dict[str, dict] = {}
    if gbp_ids:
        try:
            for g in (
                _sb().table("gbp_posts").select("id, search_url, status")
                .in_("id", gbp_ids).execute()
            ).data or []:
                gbp[g["id"]] = g
        except Exception as exc:  # pragma: no cover - best-effort
            logger.warning("paa_manifest.gbp_read_failed", extra={"error": str(exc)})

    # Syndication copies are keyed by the live source_url they were made from, so
    # a PAA post's syndication copies are the syndication_items whose source_url
    # matches that post's published_url.
    published_urls = [runs[rid].get("published_url") for rid in runs if runs[rid].get("published_url")]
    syn_by_source: dict[str, list[dict]] = {}
    if published_urls:
        try:
            for s in (
                _sb().table("syndication_items")
                .select("source_url, doc_url, sheet_url, status")
                .eq("client_id", set_row["client_id"])
                .in_("source_url", published_urls).execute()
            ).data or []:
                syn_by_source.setdefault(s["source_url"], []).append(s)
        except Exception as exc:  # pragma: no cover - best-effort
            logger.warning("paa_manifest.syndication_read_failed", extra={"error": str(exc)})

    resolved: list[dict] = []
    for it in items:
        run = runs.get(it.get("run_id") or "")
        published = (run or {}).get("published_url")
        g = gbp.get(it.get("gbp_post_id") or "")
        gbp_url = (g or {}).get("search_url") if (g or {}).get("status") == "live" else None
        syndication = []
        for s in syn_by_source.get(published or "", []):
            if s.get("doc_url"):
                syndication.append({"label": "Syndication — Google Doc", "url": s["doc_url"]})
            if s.get("sheet_url"):
                syndication.append({"label": "Syndication — Google Sheet", "url": s["sheet_url"]})
        resolved.append(
            {
                "paa_item_id": it["id"],
                "question": it.get("question"),
                "run_id": it.get("run_id"),
                "published_url": published,
                "gbp_post_id": it.get("gbp_post_id"),
                "gbp_url": gbp_url,
                "syndication": syndication,
                "image_url": None,  # per-PAA hosted images aren't tracked yet (manual row)
            }
        )
    return resolved


# ── build / refresh ───────────────────────────────────────────────────────────


def build_manifest(set_id: str, user_id: Optional[str] = None) -> dict:
    """Build or refresh the manifest for a PAA set. Idempotent: one manifest per
    set (upsert by the unique ``set_id``); a rebuild refreshes the auto content
    rows and preserves every operator-edited seed/manual row. Returns the full
    manifest view."""
    set_row = _set(set_id)
    client_id = set_row["client_id"]
    items = _items(set_id)

    # Get-or-create the manifest row (unique set_id).
    existing_m = (
        _sb().table("paa_manifests").select("*").eq("set_id", set_id).limit(1).execute()
    ).data or []
    if existing_m:
        manifest = existing_m[0]
    else:
        try:
            manifest = (
                _sb().table("paa_manifests").insert(
                    {"set_id": set_id, "client_id": client_id, "status": "draft",
                     "created_by": user_id}
                ).execute()
            ).data[0]
        except Exception:
            # The unique set_id is the race arbiter (a concurrent build won) —
            # adopt the existing row instead of surfacing a 500 on a double-click.
            rows = (
                _sb().table("paa_manifests").select("*").eq("set_id", set_id).limit(1).execute()
            ).data or []
            if not rows:
                raise
            manifest = rows[0]
    manifest_id = manifest["id"]

    resolved = _resolve_content_links(set_row, items)
    auto_rows = paa_manifest.build_content_asset_rows(resolved)

    existing_assets = (
        _sb().table("paa_manifest_assets").select("id, source")
        .eq("manifest_id", manifest_id).execute()
    ).data or []
    insert_rows, _keep_ids, delete_ids, has_seed = paa_manifest.merge_rows(auto_rows, existing_assets)

    # Refresh auto rows: drop the stale ones, re-insert from freshly-resolved links.
    if delete_ids:
        _sb().table("paa_manifest_assets").delete().in_("id", delete_ids).execute()

    to_insert = [dict(r, manifest_id=manifest_id, client_id=client_id) for r in insert_rows]
    # First build only: seed the authority bundle + the media checklist rows.
    if not has_seed:
        seed_start = len(auto_rows) + 100  # keep seeded rows below the content rows
        for r in paa_manifest.seed_authority_rows(seed_start):
            to_insert.append(dict(r, manifest_id=manifest_id, client_id=client_id))
        for r in paa_manifest.manual_media_rows(seed_start + 50):
            to_insert.append(dict(r, manifest_id=manifest_id, client_id=client_id))
    if to_insert:
        _sb().table("paa_manifest_assets").insert(to_insert).execute()

    _recompute_summaries(manifest_id)
    return get_manifest(set_id=set_id)


def _recompute_summaries(manifest_id: str) -> dict:
    """Recompute + persist the cost + QA roll-ups from the current asset rows."""
    assets = (
        _sb().table("paa_manifest_assets").select("*")
        .eq("manifest_id", manifest_id).order("position").execute()
    ).data or []
    cost_summary = paa_manifest.build_cost_summary(assets)
    qa_summary = paa_manifest.build_qa_summary(assets)
    _sb().table("paa_manifests").update(
        {"cost_summary": cost_summary, "qa_summary": qa_summary, "updated_at": "now()"}
    ).eq("id", manifest_id).execute()
    return {"cost_summary": cost_summary, "qa_summary": qa_summary}


# ── reads ─────────────────────────────────────────────────────────────────────


def get_manifest(*, set_id: Optional[str] = None, manifest_id: Optional[str] = None) -> dict:
    """The manifest view for a set (or by manifest id): the manifest row, its
    asset rows (position-ordered), the fresh client-identity header, and the
    service context. ``{exists: False}`` when a set has no manifest yet."""
    from fastapi import HTTPException

    if manifest_id:
        rows = _sb().table("paa_manifests").select("*").eq("id", manifest_id).limit(1).execute().data or []
    elif set_id:
        rows = _sb().table("paa_manifests").select("*").eq("set_id", set_id).limit(1).execute().data or []
    else:
        raise HTTPException(status_code=400, detail="set_id_or_manifest_id_required")
    if not rows:
        return {"exists": False, "set_id": set_id}
    manifest = rows[0]
    set_row = _set(manifest["set_id"])
    client = _client(manifest["client_id"])
    assets = (
        _sb().table("paa_manifest_assets").select("*")
        .eq("manifest_id", manifest["id"]).order("position").execute()
    ).data or []
    return {
        "exists": True,
        "manifest": manifest,
        "assets": assets,
        "client_identity": paa_manifest.client_identity(client),
        "service_keyword": set_row.get("service_keyword"),
        "location": set_row.get("location"),
        "cost_summary": manifest.get("cost_summary"),
        "qa_summary": manifest.get("qa_summary"),
    }


# ── asset edits (operator) ────────────────────────────────────────────────────


def _manifest_of_asset(asset_id: str) -> dict:
    from fastapi import HTTPException

    rows = (
        _sb().table("paa_manifest_assets").select("*").eq("id", asset_id).limit(1).execute()
    ).data or []
    if not rows:
        raise HTTPException(status_code=404, detail="asset_not_found")
    return rows[0]


def update_asset(asset_id: str, patch: dict) -> dict:
    """Human edit to a manifest asset (status / url / label / note / cost). Only
    whitelisted fields; recomputes the roll-ups. Returns the fresh manifest
    view."""
    asset = _manifest_of_asset(asset_id)
    clean = {k: v for k, v in (patch or {}).items() if k in _ASSET_EDITABLE}
    if clean:
        clean["updated_at"] = "now()"
        _sb().table("paa_manifest_assets").update(clean).eq("id", asset_id).execute()
    _recompute_summaries(asset["manifest_id"])
    return get_manifest(manifest_id=asset["manifest_id"])


def add_asset(manifest_id: str, body: dict) -> dict:
    """Add a manual asset row (audio/video/influencer/authority/content the
    operator captured by hand). Always ``source='manual'``."""
    from fastapi import HTTPException

    m = (
        _sb().table("paa_manifests").select("id, client_id").eq("id", manifest_id).limit(1).execute()
    ).data or []
    if not m:
        raise HTTPException(status_code=404, detail="manifest_not_found")
    category = (body.get("category") or "").strip()
    if category not in ("paa_post", "gbp_post", "syndication", "image", "authority", "media"):
        raise HTTPException(status_code=400, detail="invalid_category")
    label = (body.get("label") or "").strip()
    if not label:
        raise HTTPException(status_code=400, detail="label_required")
    # Position after everything currently present.
    existing = (
        _sb().table("paa_manifest_assets").select("position")
        .eq("manifest_id", manifest_id).order("position", desc=True).limit(1).execute()
    ).data or []
    next_pos = ((existing[0]["position"] if existing else 0) or 0) + 1
    row = {
        "manifest_id": manifest_id,
        "client_id": m[0]["client_id"],
        "category": category,
        "source": "manual",
        "kind": (body.get("kind") or "").strip() or None,
        "label": label,
        "url": (body.get("url") or "").strip() or None,
        "note": (body.get("note") or "").strip() or None,
        "status": (body.get("status") or "planned").strip(),
        "confidence_tag": (body.get("confidence_tag") or "").strip() or None,
        "cost_task_type": (body.get("cost_task_type") or "").strip() or None,
        "cost_quantity": body.get("cost_quantity"),
        "position": next_pos,
    }
    _sb().table("paa_manifest_assets").insert(row).execute()
    _recompute_summaries(manifest_id)
    return get_manifest(manifest_id=manifest_id)


def delete_asset(asset_id: str) -> dict:
    asset = _manifest_of_asset(asset_id)
    _sb().table("paa_manifest_assets").delete().eq("id", asset_id).execute()
    _recompute_summaries(asset["manifest_id"])
    return get_manifest(manifest_id=asset["manifest_id"])


# ── QA (async job) ────────────────────────────────────────────────────────────


def enqueue_qa(manifest_id: str) -> Optional[str]:
    """Enqueue one ``paa_manifest_qa`` job for a manifest; a live one is reused
    (idempotent)."""
    from fastapi import HTTPException

    m = (
        _sb().table("paa_manifests").select("id").eq("id", manifest_id).limit(1).execute()
    ).data or []
    if not m:
        raise HTTPException(status_code=404, detail="manifest_not_found")

    live = (
        _sb().table("async_jobs").select("id")
        .eq("job_type", "paa_manifest_qa").eq("entity_id", manifest_id)
        .in_("status", ["pending", "running"]).limit(1).execute()
    ).data or []
    if live:
        return live[0]["id"]
    job = (
        _sb().table("async_jobs").insert(
            {"job_type": "paa_manifest_qa", "entity_id": manifest_id,
             "payload": {"manifest_id": manifest_id}}
        ).execute()
    ).data[0]
    return job["id"]


def _deterministic_verdict(checks: Optional[dict]) -> Optional[str]:
    """v1's free deterministic fallback: a 'pass' when the item cleared BOTH the
    exact-match and the service-page-link check (the two things that make a PAA
    page worth amplifying), else 'revisions'. None when the item wasn't verified
    yet. Used when the QA Agent is disabled (``qa_enabled`` False)."""
    if not checks:
        return None
    em = (checks.get("exact_match") or {})
    sl = (checks.get("service_link") or {})
    ok = bool(em.get("ok")) and (sl.get("ok") in (True, None))
    return "pass" if ok else "revisions"


async def run_manifest_qa_job(job: dict) -> None:
    """Async-job entry: QA each content asset that has a live URL, roll up.

    With ``qa_enabled`` on, calls the QA Agent's bare-URL path
    (``qa_service.review_url``) with the blog rubric per PAA-post / syndication
    URL (the content the authority layer amplifies). With it off, falls back to
    v1's deterministic per-item exact-match / service-link verdict. GBP posts +
    images are not URL-gradeable → left for human attestation."""
    payload = job.get("payload") or {}
    manifest_id = payload.get("manifest_id")
    if not manifest_id:
        raise ValueError("paa_manifest_qa: missing manifest_id")

    m = (
        _sb().table("paa_manifests").select("id, set_id, client_id")
        .eq("id", manifest_id).limit(1).execute()
    ).data or []
    if not m:
        logger.warning("paa_manifest_qa.manifest_gone", extra={"manifest_id": manifest_id})
        return
    set_row = _set(m[0]["set_id"])
    client = _client(m[0]["client_id"])
    assets = (
        _sb().table("paa_manifest_assets").select("*")
        .eq("manifest_id", manifest_id).order("position").execute()
    ).data or []

    from datetime import datetime, timezone

    now_iso = datetime.now(timezone.utc).isoformat()
    reviewed = 0
    for a in assets:
        rubric = paa_manifest.qa_rubric_for(a.get("category"))
        if rubric is None:
            continue  # gbp_post / image — not URL-gradeable
        url = (a.get("url") or "").strip()
        verdict: Optional[str] = None
        review: Optional[dict] = None
        if url and settings.qa_enabled:
            try:
                from services import qa_service

                result = await qa_service.review_url(
                    url, client=client, rubric=rubric,
                    keyword=set_row.get("service_keyword"),
                )
                verdict = result.get("verdict")
                review = {
                    "mode": "qa_agent",
                    "rubric": result.get("rubric"),
                    "composite": result.get("composite"),
                    "issues": result.get("issues"),
                    "narrative": result.get("narrative"),
                }
            except Exception as exc:
                logger.warning("paa_manifest_qa.review_failed",
                               extra={"asset_id": a.get("id"), "error": str(exc)})
        elif a.get("paa_item_id"):
            # QA Agent off (or no live URL yet) → v1's free deterministic checks.
            item = (
                _sb().table("paa_items").select("checks")
                .eq("id", a["paa_item_id"]).limit(1).execute()
            ).data or []
            checks = (item[0].get("checks") if item else None) or None
            det = _deterministic_verdict(checks)
            if det:
                verdict, review = det, {"mode": "deterministic", "checks": checks}
        if verdict:
            reviewed += 1
            _sb().table("paa_manifest_assets").update(
                {"qa_verdict": verdict, "qa_review": review, "qa_reviewed_at": now_iso,
                 "updated_at": "now()"}
            ).eq("id", a["id"]).execute()

    _recompute_summaries(manifest_id)
    # A manifest that has had its content QA'd is 'ready' to hand off.
    if reviewed:
        _sb().table("paa_manifests").update({"status": "ready", "updated_at": "now()"}).eq(
            "id", manifest_id
        ).execute()
    logger.info("paa_manifest_qa.done", extra={"manifest_id": manifest_id, "reviewed": reviewed})


# ── export / hand-off ─────────────────────────────────────────────────────────


def build_export(manifest_id: str) -> dict:
    """Assemble the export artifacts (pure rows + JSON payload) for a manifest.
    Returns ``{title, rows, payload}``. The router serializes CSV/JSON from this;
    the Sheet export (below) writes ``rows`` to Drive."""
    from datetime import datetime, timezone

    view = get_manifest(manifest_id=manifest_id)
    if not view.get("exists"):
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="manifest_not_found")
    identity = view["client_identity"]
    assets = view["assets"]
    service_keyword = view.get("service_keyword") or ""
    location = view.get("location") or ""
    rows = paa_manifest.export_rows(identity, assets, service_keyword=service_keyword,
                                    location=location)
    payload = paa_manifest.export_payload(
        manifest=view["manifest"], identity=identity, assets=assets,
        cost_summary=view.get("cost_summary") or {}, qa_summary=view.get("qa_summary") or {},
        service_keyword=service_keyword, location=location,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
    title = f"PAA Prep Sheet — {service_keyword}" + (f" ({location})" if location else "")
    return {"title": title, "rows": rows, "payload": payload}


async def export_to_sheet(manifest_id: str) -> dict:
    """Write the manifest to a Google Sheet in the client's Drive folder (the
    hand-off artifact; reference §3). Reuses ``google_docs.create_google_sheet``.
    Marks the manifest ``handed_off`` + records the Sheet refs."""
    from fastapi import HTTPException

    from services import google_docs

    view = get_manifest(manifest_id=manifest_id)
    if not view.get("exists"):
        raise HTTPException(status_code=404, detail="manifest_not_found")
    client = _client(view["manifest"]["client_id"])
    folder = google_docs.resolve_drive_folder(client, "paa_manifest") or client.get("google_drive_folder_id")
    if not folder:
        raise HTTPException(status_code=400, detail="missing_google_drive_folder_id")

    export = build_export(manifest_id)
    rows = [[str(c) for c in row] for row in export["rows"]]
    result = await google_docs.create_google_sheet(
        folder, export["title"], rows, share="link", dedupe_by_name=True
    )
    from datetime import datetime, timezone

    _sb().table("paa_manifests").update(
        {"sheet_id": result.get("sheet_id"), "sheet_url": result.get("sheet_url"),
         "last_export_at": datetime.now(timezone.utc).isoformat(),
         "status": "handed_off", "updated_at": "now()"}
    ).eq("id", manifest_id).execute()
    return {"sheet_id": result.get("sheet_id"), "sheet_url": result.get("sheet_url"),
            "reused": result.get("reused", False)}
