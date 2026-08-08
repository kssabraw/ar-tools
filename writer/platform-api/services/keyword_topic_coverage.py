"""Keyword Research — Topic Research coverage tagging.

A topic plan is more useful on an ongoing basis if it tells you which topics are
NET-NEW versus ones the client already has content for. This tags each topic card
``coverage: 'gap' | 'covered'`` by matching it against the client's existing
content inventory — the themes already on their site plus their published
blog/service runs and Local SEO pages — so a re-run surfaces the GAPS, not repeats.

Deterministic (token overlap), best-effort, and advisory: a 'covered' tag means
"you likely already have a base for this" (the strategist often plans these as
upgrades), not "skip it". Pure matching is unit-tested; the inventory read is the
only I/O.
"""

from __future__ import annotations

import logging
from typing import Optional

from db.supabase_client import get_supabase
from services import keyword_research

logger = logging.getLogger(__name__)

_MIN_OVERLAP = 2  # distinctive tokens a card must share with an existing item to be "covered"


# ---------------------------------------------------------------------------
# Pure matching — independently unit-tested.
# ---------------------------------------------------------------------------
def _card_tokens(card: dict) -> set[str]:
    """The topic tokens of a card: its title + theme/pillar (the topic identity,
    not every supporting keyword — those broaden the match too far). Pure."""
    return (keyword_research.token_set(card.get("title"))
            | keyword_research.token_set(card.get("theme"))
            | keyword_research.token_set(card.get("pillar")))


def is_covered(card: dict, existing: list[set[str]], min_overlap: int = _MIN_OVERLAP) -> bool:
    """Whether an existing content item covers this card's topic — it shares at
    least ``min_overlap`` significant tokens with the card's title/theme. Pure."""
    ct = _card_tokens(card)
    if len(ct) < min_overlap:
        return False
    for ex in existing:
        if len(ct & ex) >= min_overlap:
            return True
    return False


def tag_coverage(cards: list[dict], existing_texts: list[str],
                 min_overlap: int = _MIN_OVERLAP) -> tuple[list[dict], dict]:
    """Attach ``coverage`` ('gap' | 'covered') to every card. Returns (cards,
    report={gap, covered}). Pure — the caller gathers ``existing_texts``."""
    existing = [ts for ts in (keyword_research.token_set(t) for t in existing_texts) if ts]
    gap = covered = 0
    out: list[dict] = []
    for c in cards:
        tag = "covered" if is_covered(c, existing, min_overlap) else "gap"
        out.append({**c, "coverage": tag})
        if tag == "covered":
            covered += 1
        else:
            gap += 1
    return out, {"gap": gap, "covered": covered}


# ---------------------------------------------------------------------------
# Inventory read (I/O) — best-effort.
# ---------------------------------------------------------------------------
def gather_existing_content(client_id: str, site_topics: Optional[list[str]] = None) -> list[str]:
    """The client's existing content inventory as text phrases: their site themes +
    completed blog/service run keywords + Local SEO page keywords/titles. Best-effort
    — a failing source contributes nothing."""
    texts: list[str] = list(site_topics or [])
    supabase = get_supabase()
    try:
        runs = (supabase.table("runs").select("keyword")
                .eq("client_id", client_id).eq("status", "complete")
                .limit(500).execute()).data or []
        texts += [r.get("keyword") for r in runs if r.get("keyword")]
    except Exception as exc:  # noqa: BLE001
        logger.warning("keyword_topic_coverage.runs_failed", extra={"error": str(exc)})
    try:
        pages = (supabase.table("local_seo_pages").select("keyword, title")
                 .eq("client_id", client_id).is_("deleted_at", "null")
                 .limit(500).execute()).data or []
        for p in pages:
            if p.get("keyword"):
                texts.append(p["keyword"])
            if p.get("title"):
                texts.append(p["title"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("keyword_topic_coverage.pages_failed", extra={"error": str(exc)})
    # Dedupe (case-insensitive), drop blanks.
    seen: set[str] = set()
    out: list[str] = []
    for t in texts:
        s = (t or "").strip()
        low = s.lower()
        if s and low not in seen:
            seen.add(low)
            out.append(s)
    return out
