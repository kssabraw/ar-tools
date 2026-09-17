"""PAA → SEO Neo Phase 2 — pure helpers for the prep-sheet MANIFEST.

The methodology's physical hand-off is the **prep sheet** (reference §3): one
artifact per service-in-geo carrying the client's identity (NAP / CID / place
ID / GBP URL) + **every** asset URL the campaign produced, routed to a link
operator. The one real org gap the source flags is *"agree explicitly who
captures the asset URLs and hands them off."* Phase 2 makes the suite that
capturer — a **manifest** that auto-collects what the suite already produced,
tracks the human/authority work as checklist rows, costs it (reused Recipe
Engine), QAs the content (reused QA Agent, in the impure layer), and exports it.

This module holds the PURE (no-I/O) helpers — the seeded authority bundle, the
manual-media rows, content-row assembly from already-resolved links, the
Recipe-Engine cost rollup, the QA rollup, and the CSV/Sheet/JSON export
rendering. The I/O (resolving live URLs, the DB, the QA-Agent calls, the Sheet
export) lives in ``services/paa_manifest_service.py``.

PERMANENT GUARDRAIL (PRD §9): the suite tracks / costs / QAs / hands off a
manifest — it **NEVER executes** the SEO Neo authority layer (link blasts /
RD 100 / GMBB Blast / Omega / PBNs). The seeded authority rows are tracked-only:
there is deliberately no "execute" affordance anywhere; a row's status is
human-set (planned → handed_off → done). Confidence tags
(``[PROVEN]``/``[THEORY]``/``[BELIEF]``) are carried into every user-facing
surface — the methodology is one group's working model, not Google guidance.

Reuse (PRD §7 — don't rebuild): ``recipe_engine.price_catalog`` / ``cost_of``
for costing the authority bundle (honest "not estimated" for off-menu RD 100).
"""

from __future__ import annotations

from typing import Iterable, Optional

from services.recipe_engine import cost_of, price_catalog

__all__ = [
    "AUTHORITY_BUNDLE",
    "MANUAL_MEDIA_ROWS",
    "CONTENT_CATEGORIES",
    "QA_SEVERITY",
    "GUARDRAIL_NOTE",
    "client_identity",
    "is_content_asset",
    "qa_rubric_for",
    "seed_authority_rows",
    "manual_media_rows",
    "build_content_asset_rows",
    "merge_rows",
    "build_cost_summary",
    "build_qa_summary",
    "qa_worst",
    "export_columns",
    "export_rows",
    "export_payload",
]

# Content classes = what the authority layer amplifies (the QA target). authority
# = a tracked link-layer line item (never executed). media = audio/video/
# influencer (never generated).
CONTENT_CATEGORIES = frozenset({"paa_post", "gbp_post", "syndication", "image"})

# Most-severe → least, for the QA rollup's `worst`. 'pending' = has no live URL to
# review yet (not a failure). 'skipped' = a category QA doesn't grade. The
# manifest's own item verdicts are pass/'revisions'; a real QA review folded in
# (paa_manifest_qa → qa_service) also carries 'minor_'/'major_revisions'.
QA_SEVERITY = [
    "fail", "needs_human", "major_revisions", "minor_revisions", "revisions",
    "advisory", "pass", "skipped", "pending",
]

# Carried onto every export + the manifest UI — the load-bearing boundary.
GUARDRAIL_NOTE = (
    "Authority-layer items are OFF-PLATFORM vendor work — tracked here, NEVER "
    "executed by the suite. Confidence tags ([PROVEN]/[THEORY]/[BELIEF]) are the "
    "methodology's own; they are one local-SEO group's working model, not Google "
    "guidance."
)


# ── the seeded authority bundle (reference §5.1 — the 7 seam bolts) ───────────
# Each is a tracked-only row. `cost_task_type` maps to a recipe_engine
# price_catalog() key when one exists (so the row costs), else None → the row
# shows "not estimated" (honest — RD 100 is deliberately off the Recipe Engine's
# default menu, and its 100:1 ratio is [THEORY]/disputed). `tag` is the
# methodology's confidence marker.
AUTHORITY_BUNDLE: list[dict] = [
    {
        "kind": "neo_bucket",
        "label": "SEO Neo content buckets (one per PAA — embed the PAA's image + video)",
        "tag": "PROVEN",
        "cost_task_type": None,
        "note": "Bolt 1 — PAA articles feed Neo content buckets, per service/PAA.",
    },
    {
        "kind": "wiki_cloud_stack",
        "label": "Wiki / cloud stacks embedding the exact PAA article",
        "tag": "PROVEN",
        "cost_task_type": "cloud_stack",
        "note": "Bolt 4 — stack authority ONTO the asset (wikis are the strongest link group).",
    },
    {
        "kind": "rd_100",
        "label": "RD 100 to the PAA posts + the tier ones (full PAA as anchor text)",
        "tag": "THEORY",
        "cost_task_type": None,  # off the Recipe Engine's default menu — no fake $
        "note": "Bolts 2 & 6 — the 100:1 ratio is one contributor's model, openly "
                "disputed in the source (a common alternative is ~50 RDs). Off the "
                "Recipe Engine's default menu → not cost-estimated here.",
    },
    {
        "kind": "gmbb_blast",
        "label": "GMBB Blast to the service's directional URLs (map-only — never the money URL)",
        "tag": "PROVEN",
        "cost_task_type": "gbp_blast",
        "note": "Bolt 3 — a parallel map-only amplifier (Google's own map assets). "
                "Keep each blast to ONE service; never RD 100 + a Blast on the same "
                "money URL at once.",
    },
    {
        "kind": "rank_your_brand",
        "label": "Rank Your Brand tier-3 (LSI / entity anchors) fed by the PAAs",
        "tag": "THEORY",
        "cost_task_type": None,
        "note": "Bolt 5 — LSI/entity anchor tier fed by the PAA strings.",
    },
    {
        "kind": "press_release",
        "label": "Press release (a maps play — used as tier-one / RD-100 targets)",
        "tag": "PROVEN",
        "cost_task_type": None,
        "note": "Reference §6 — hundreds of referring domains + News-tab coverage.",
    },
]

# audio / video / influencer — human-produced + human-proofed. Tracked as
# checklist rows; the suite NEVER generates them (PRD §9, decision #3).
MANUAL_MEDIA_ROWS: list[dict] = [
    {
        "kind": "audio",
        "label": "Podcast / audio syndication (produced from the PAA blog)",
        "tag": "PROVEN",
        "note": "Reference §7 — one upload → ~13 syndicated brand links + a knowledge "
                "panel. An authority play, not an audience play. Human-produced.",
    },
    {
        "kind": "video",
        "label": "Video (the production hub — supplies the audio + the reels)",
        "tag": "BELIEF",
        "note": "Reference §7 — the one inferred seam (SOP 07c not sourced). "
                "Human-produced + human-proofed.",
    },
    {
        "kind": "influencer",
        "label": "Real footage + influencer endorsement (permanent embedded backlink)",
        "tag": "PROVEN",
        "note": "Reference §7 — a 'real human' signal AI can't fake; the embedded "
                "endorsement + backlink is the SEO deliverable. Human-produced.",
    },
]


# ── client identity header (read fresh, never stored) ─────────────────────────


def client_identity(client: Optional[dict]) -> dict:
    """The prep-sheet identity header (reference §3) from the client row's GBP
    capture. NAP + CID + place ID + GBP URL + website — the constant part of the
    sheet the operator needs. Pure. Missing fields come back as ``""`` so the
    export renders cleanly."""
    client = client or {}
    gbp = client.get("gbp") or {}
    name = (gbp.get("business_name") or client.get("name") or "").strip()
    return {
        "business_name": name,
        "address": (gbp.get("address") or gbp.get("full_address") or "").strip(),
        "phone": (gbp.get("phone") or "").strip(),
        "place_id": (gbp.get("place_id") or gbp.get("google_id") or "").strip(),
        "cid": str(gbp.get("cid") or "").strip(),
        "gbp_url": (gbp.get("google_maps_uri") or gbp.get("google_maps_url") or "").strip(),
        "website": (client.get("website_url") or gbp.get("website") or "").strip(),
    }


# ── category helpers ──────────────────────────────────────────────────────────


def is_content_asset(category: Optional[str]) -> bool:
    """True for a content class the authority layer amplifies (the QA target)."""
    return category in CONTENT_CATEGORIES


def qa_rubric_for(category: Optional[str]) -> Optional[str]:
    """The QA-Agent rubric to grade a content asset's live URL with, or None when
    the category isn't URL-gradeable. Pure.

    Only page-like content is auto-QA'd: a PAA post and a syndication copy are
    articles (``blog``). A GBP post's ``search_url`` is a JS-heavy Google Maps
    post page (not gradeable), and an image isn't a page — both return None and
    are left to human attestation."""
    if category in ("paa_post", "syndication"):
        return "blog"
    return None


# ── seeded + manual rows (ready-to-insert dicts, minus manifest_id/client_id) ──


def _row(**kw) -> dict:
    """A manifest-asset row with the module's defaults filled in. Pure."""
    base = {
        "category": kw["category"],
        "source": kw.get("source", "manual"),
        "kind": kw.get("kind"),
        "label": kw["label"],
        "url": kw.get("url"),
        "note": kw.get("note"),
        "status": kw.get("status", "collected"),
        "confidence_tag": kw.get("confidence_tag"),
        "cost_task_type": kw.get("cost_task_type"),
        "cost_quantity": kw.get("cost_quantity"),
        "paa_item_id": kw.get("paa_item_id"),
        "position": kw.get("position", 0),
    }
    return base


def seed_authority_rows(start_position: int = 0) -> list[dict]:
    """The standard authority bundle as ``source='seed'``, ``status='planned'``,
    tracked-only rows (§11.1.3). Each maps to a Recipe-Engine cost where one
    exists (quantity 1 as the planning default) and carries its confidence tag.
    Pure."""
    out: list[dict] = []
    for i, item in enumerate(AUTHORITY_BUNDLE):
        out.append(
            _row(
                category="authority",
                source="seed",
                kind=item["kind"],
                label=item["label"],
                note=item["note"],
                status="planned",
                confidence_tag=item["tag"],
                cost_task_type=item["cost_task_type"],
                cost_quantity=1 if item["cost_task_type"] else None,
                position=start_position + i,
            )
        )
    return out


def manual_media_rows(start_position: int = 0) -> list[dict]:
    """The audio/video/influencer checklist rows as ``source='seed'`` (they ship
    with the manifest), ``category='media'``, ``status='planned'``, never a
    generator. Pure."""
    out: list[dict] = []
    for i, item in enumerate(MANUAL_MEDIA_ROWS):
        out.append(
            _row(
                category="media",
                source="seed",
                kind=item["kind"],
                label=item["label"],
                note=item["note"],
                status="planned",
                confidence_tag=item["tag"],
                position=start_position + i,
            )
        )
    return out


# ── content-row assembly (pure — the service resolves the live links) ─────────


def build_content_asset_rows(resolved_items: Iterable[dict], start_position: int = 0) -> list[dict]:
    """Assemble the auto-collected content-asset rows from already-resolved v1
    linkage. Pure — the impure layer supplies the resolved links.

    Each ``resolved_items`` entry is one chosen PAA item, shape::

        {
          "paa_item_id": str, "question": str,
          "run_id": str | None, "published_url": str | None,
          "gbp_post_id": str | None, "gbp_url": str | None,
          "syndication": [{"label": str, "url": str}, ...],
          "image_url": str | None,
        }

    Emits, per item: one ``paa_post`` row (live URL if published, else
    ``status='pending'`` when a run exists), a ``gbp_post`` row when a live GBP
    URL is known, one ``syndication`` row per copy, and an ``image`` row when a
    hosted image URL is known. All ``source='auto'`` (refreshed on rebuild).
    """
    out: list[dict] = []
    pos = start_position
    for item in resolved_items or []:
        q = (item.get("question") or "").strip()
        paa_item_id = item.get("paa_item_id")
        run_id = item.get("run_id")
        published = (item.get("published_url") or "").strip() or None
        # PAA post — the primary content asset. pending until it's published live
        # (you QA + hand off after publish); missing when no run exists at all.
        if published:
            status = "collected"
        elif run_id:
            status = "pending"
        else:
            status = "missing"
        out.append(
            _row(
                category="paa_post",
                source="auto",
                kind="paa_blog",
                label=f"PAA post — {q}" if q else "PAA post",
                url=published,
                status=status,
                note=None if published else (
                    "run created but not published live yet — publish to enable QA + hand-off"
                    if run_id else "no post created for this question yet"
                ),
                paa_item_id=paa_item_id,
                position=pos,
            )
        )
        pos += 1
        gbp_url = (item.get("gbp_url") or "").strip() or None
        if item.get("gbp_post_id") or gbp_url:
            out.append(
                _row(
                    category="gbp_post",
                    source="auto",
                    kind="gbp_post",
                    label=f"GBP post — {q}" if q else "GBP post",
                    url=gbp_url,
                    status="collected" if gbp_url else "pending",
                    note=None if gbp_url else "GBP draft created — publish to capture the live URL",
                    paa_item_id=paa_item_id,
                    position=pos,
                )
            )
            pos += 1
        for syn in item.get("syndication") or []:
            url = (syn.get("url") or "").strip() or None
            out.append(
                _row(
                    category="syndication",
                    source="auto",
                    kind="syndication_copy",
                    label=syn.get("label") or "Syndication copy",
                    url=url,
                    status="collected" if url else "pending",
                    paa_item_id=paa_item_id,
                    position=pos,
                )
            )
            pos += 1
        image_url = (item.get("image_url") or "").strip() or None
        if image_url:
            out.append(
                _row(
                    category="image",
                    source="auto",
                    kind="hosted_image",
                    label=f"Hosted image — {q}" if q else "Hosted image",
                    url=image_url,
                    status="collected",
                    note="reuse as the Neo bucket image (reference §7 — SOP 10 seam)",
                    paa_item_id=paa_item_id,
                    position=pos,
                )
            )
            pos += 1
    return out


def merge_rows(
    auto_rows: list[dict], existing: list[dict]
) -> tuple[list[dict], list[str], list[str], bool]:
    """Rebuild reconciliation: refresh the auto content rows, PRESERVE every
    human-touched row (seed authority/media + manual rows keep their status,
    URLs, notes, and QA). Pure.

    Returns ``(insert_rows, keep_ids, delete_ids, has_seed)``:
      * every current ``source='auto'`` row is deleted (``delete_ids``) +
        re-inserted from the freshly-resolved ``auto_rows`` (so a newly-published
        URL / QA is picked up) — a rebuild never clobbers operator edits because
        those live on ``source in ('seed','manual')`` rows;
      * ``source in ('seed','manual')`` rows are kept as-is (``keep_ids``);
      * ``has_seed`` is True when the seeded authority/media bundle already
        exists, so the caller seeds it ONLY on the first build (never re-seeds
        duplicates on a rebuild).
    """
    keep_ids: list[str] = []
    delete_ids: list[str] = []
    has_seed = False
    for row in existing or []:
        if row.get("source") == "auto":
            delete_ids.append(row["id"])
        else:
            keep_ids.append(row["id"])
            if row.get("source") == "seed":
                has_seed = True
    insert_rows = list(auto_rows)
    return insert_rows, keep_ids, delete_ids, has_seed


# ── cost rollup (reused Recipe Engine) ────────────────────────────────────────


def build_cost_summary(assets: Iterable[dict]) -> dict:
    """Cost the authority bundle from the reused Recipe-Engine catalog. Pure.

    Only rows carrying a ``cost_task_type`` that maps to a
    ``recipe_engine.price_catalog()`` entry contribute a dollar line; every other
    authority/media row is listed under ``not_estimated`` (honest — off-menu
    RD 100 has no priced entry, and its disputed 100:1 ratio is surfaced without
    a fake number). Returns
    ``{estimated_total, lines, not_estimated, currency}``."""
    catalog = price_catalog()
    lines: list[dict] = []
    not_estimated: list[dict] = []
    costed_items: list[dict] = []
    for a in assets or []:
        if a.get("category") not in ("authority", "media"):
            continue
        task_type = a.get("cost_task_type")
        entry = catalog.get(task_type) if task_type else None
        if not entry:
            not_estimated.append({"label": a.get("label"), "kind": a.get("kind"),
                                  "confidence_tag": a.get("confidence_tag")})
            continue
        try:
            qty = float(a.get("cost_quantity") or 0)
        except (TypeError, ValueError):
            qty = 0.0
        if qty <= 0:
            not_estimated.append({"label": a.get("label"), "kind": a.get("kind"),
                                  "confidence_tag": a.get("confidence_tag")})
            continue
        costed_items.append({"task_type": task_type, "quantity": qty})
        lines.append({
            "label": a.get("label"),
            "task_type": task_type,
            "quantity": qty,
            "unit_cost": entry["unit_cost"],
            "line_cost": round(entry["unit_cost"] * qty, 2),
        })
    total = cost_of(costed_items, catalog)  # None when nothing mapped
    return {
        "estimated_total": total,
        "lines": lines,
        "not_estimated": not_estimated,
        "currency": "USD",
    }


# ── QA rollup ─────────────────────────────────────────────────────────────────


def qa_worst(verdicts: Iterable[Optional[str]]) -> Optional[str]:
    """The most-severe verdict present (fail > needs_human > revisions > advisory
    > pass), ignoring pending/skipped/None. Returns None when nothing is graded
    yet. Pure."""
    present = {v for v in verdicts if v in QA_SEVERITY and v not in ("pending", "skipped")}
    for sev in QA_SEVERITY:
        if sev in present:
            return sev
    return None


def build_qa_summary(assets: Iterable[dict]) -> dict:
    """Roll up content-asset QA verdicts (§11.1.4). Pure.

    Counts only the content classes the authority layer amplifies. A content
    asset with a live URL and a stored verdict is ``reviewed``; one with a URL
    the QA gate hasn't graded (or no live URL yet) is ``pending``; a category QA
    doesn't grade (gbp_post/image) is ``not_applicable``. ``worst`` drives the
    manifest's headline QA state (green only when all reviewed content passed)."""
    counts: dict[str, int] = {}
    content = 0
    reviewed = 0
    pending = 0
    not_applicable = 0
    verdicts: list[Optional[str]] = []
    for a in assets or []:
        if not is_content_asset(a.get("category")):
            continue
        content += 1
        if qa_rubric_for(a.get("category")) is None:
            not_applicable += 1
            continue
        v = a.get("qa_verdict")
        if v and v not in ("pending", "skipped"):
            reviewed += 1
            counts[v] = counts.get(v, 0) + 1
            verdicts.append(v)
        else:
            pending += 1
    return {
        "content_assets": content,
        "reviewed": reviewed,
        "pending": pending,
        "not_applicable": not_applicable,
        "verdicts": counts,
        "worst": qa_worst(verdicts),
    }


# ── export rendering (CSV / Sheet rows + JSON) ────────────────────────────────

export_columns = [
    "Category", "Source", "Item", "URL", "Status", "Confidence",
    "QA verdict", "Est. cost", "Notes",
]


def _cost_cell(asset: dict, catalog: dict) -> str:
    task_type = asset.get("cost_task_type")
    entry = catalog.get(task_type) if task_type else None
    if not entry:
        return "not estimated" if asset.get("category") in ("authority", "media") else ""
    try:
        qty = float(asset.get("cost_quantity") or 0)
    except (TypeError, ValueError):
        qty = 0.0
    if qty <= 0:
        return "not estimated"
    return f"${round(entry['unit_cost'] * qty, 2):.2f}"


def export_rows(identity: dict, assets: list[dict], *, service_keyword: str = "",
                location: str = "") -> list[list[str]]:
    """The prep-sheet as rows (list[list[str]]) for a Google Sheet / CSV. Pure.

    Starts with the client-identity header block (reference §3), a spacer, the
    guardrail note, then the column header + one row per asset (grouped
    content → authority → media by the caller's ordering). Every cell is a
    string so the Sheet webhook + ``csv`` writer take it verbatim."""
    catalog = price_catalog()
    rows: list[list[str]] = []
    rows.append(["PAA → SEO Neo — Prep Sheet"])
    if service_keyword:
        rows.append(["Service", service_keyword] + ([location] if location else []))
    rows.append(["Business", identity.get("business_name", "")])
    rows.append(["Address", identity.get("address", "")])
    rows.append(["Phone", identity.get("phone", "")])
    rows.append(["Place ID", identity.get("place_id", "")])
    rows.append(["CID", identity.get("cid", "")])
    rows.append(["GBP URL", identity.get("gbp_url", "")])
    rows.append(["Website", identity.get("website", "")])
    rows.append([])
    rows.append([GUARDRAIL_NOTE])
    rows.append([])
    rows.append(list(export_columns))
    for a in assets or []:
        tag = a.get("confidence_tag")
        rows.append([
            a.get("category") or "",
            a.get("source") or "",
            a.get("label") or "",
            a.get("url") or "",
            a.get("status") or "",
            f"[{tag}]" if tag else "",
            a.get("qa_verdict") or "",
            _cost_cell(a, catalog),
            a.get("note") or "",
        ])
    return rows


def export_payload(
    *, manifest: dict, identity: dict, assets: list[dict],
    cost_summary: dict, qa_summary: dict, service_keyword: str = "",
    location: str = "", generated_at: str = "",
) -> dict:
    """The manifest as a JSON hand-off object. Pure — ``generated_at`` is passed
    in so the helper stays deterministic."""
    return {
        "prep_sheet": "PAA → SEO Neo",
        "generated_at": generated_at,
        "service_keyword": service_keyword,
        "location": location,
        "guardrail": GUARDRAIL_NOTE,
        "client_identity": identity,
        "status": manifest.get("status"),
        "cost_summary": cost_summary,
        "qa_summary": qa_summary,
        "assets": [
            {
                "category": a.get("category"),
                "source": a.get("source"),
                "kind": a.get("kind"),
                "label": a.get("label"),
                "url": a.get("url"),
                "status": a.get("status"),
                "confidence_tag": a.get("confidence_tag"),
                "cost_task_type": a.get("cost_task_type"),
                "cost_quantity": a.get("cost_quantity"),
                "qa_verdict": a.get("qa_verdict"),
                "note": a.get("note"),
            }
            for a in assets or []
        ],
    }
