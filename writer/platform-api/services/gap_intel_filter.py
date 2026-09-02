"""Domain-Intelligence keyword-gap quality filter — the single chokepoint that
keeps junk gap keywords off the Action Plan, the PM board, and PACE.

A domain-intel keyword gap becomes a "build / strengthen a page for this term"
Action Plan item, which the auto-producer + the PACE hand-off turn into a board
task. Some gaps are never content targets:

  * navigational / portal / account lookups ("sedgwick phone number", "mysedgwick
    portal"), street addresses, and competitor-brand terms — the DETERMINISTIC
    layer (``keyword_research_navigational``) already names these; and
  * a competitor's coined PRODUCT / BRAND token — "autoclaims", "timeoff",
    "absenceone" (Sedgwick products), "tas-k" — which exact-token rules can't
    separate from a legitimate one-word service gap ("plumbing") without
    semantics. All of these share a signature: the client ranks nowhere and a
    (often registered) competitor ranks for a bare brand/product name.

This module layers a best-effort LLM judgement (one cheap batched call per
rebuild) on top of the deterministic gate, so the coined product-brand class the
rules can't name is caught WITHOUT per-term registry whack-a-mole. It is the one
place the plan builder filters gap keywords, so every client + PACE are protected
uniformly.

Best-effort throughout: a missing LLM key, a disabled flag, or a failed call
degrades to the deterministic gate only — it never drops a legitimate gap and
never blocks the plan.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import keyword_research_navigational as krn

logger = logging.getLogger(__name__)


def _norm(s: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


# ---------------------------------------------------------------------------
# Deterministic layer (pure) — reuses the shared navigational/brand/address rules.
# ---------------------------------------------------------------------------
def deterministic_verdict(keyword: Optional[str], matchers: list[set[str]]) -> str:
    """'navigational' | 'competitor' | 'address' | 'keep'. Pure. The competitor
    layer needs ``matchers`` (the client's brand token-sets); an empty list means
    navigational + address only."""
    tag = krn.classify_intent(keyword, matchers)
    if tag in ("navigational", "competitor"):
        return tag
    if krn.is_address(keyword):
        return "address"
    return "keep"


# ---------------------------------------------------------------------------
# LLM layer (I/O via the shared report_llm transport) — best-effort.
# ---------------------------------------------------------------------------
_GAP_SYSTEM = (
    "You are an SEO content strategist. You are given a business and a list of "
    "keywords a COMPETITOR ranks for but the business does not. Your job is to "
    "flag the keywords that are NOT worth building a content page for because they "
    "are not a real content topic for THIS business. Flag a keyword ONLY when it "
    "is clearly one of: (a) a specific company's brand or PRODUCT name (including "
    "run-together product names like 'autoclaims', 'timeoff', 'absenceone', or a "
    "competitor's app/portal name); (b) a login / portal / account / support "
    "lookup; (c) a person's name, a street address, or a phone number; or (d) an "
    "otherwise navigational query someone types to REACH a specific company. Do "
    "NOT flag a genuine service, product-category, or informational topic the "
    "business could rank for (e.g. 'claims outsourcing', 'commercial roof repair', "
    "'workers comp administration'). When unsure, KEEP the keyword — only flag the "
    "clear non-topics."
)
_GAP_TOOL = {
    "name": "emit_non_topics",
    "description": "Return the keywords that are NOT a content topic for this business.",
    "input_schema": {
        "type": "object",
        "properties": {
            "not_content_keywords": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "keyword": {"type": "string", "description": "Verbatim keyword from the list."},
                        "reason": {
                            "type": "string",
                            "description": "brand_or_product | navigational | person_or_address | other",
                        },
                    },
                    "required": ["keyword", "reason"],
                },
                "description": "The subset of the provided keywords that are brand/product "
                "names, navigational lookups, or otherwise not a content topic. Empty if "
                "every keyword is a genuine topic.",
            },
        },
        "required": ["not_content_keywords"],
    },
}


def _client_description(client: dict) -> str:
    parts = [f"Business name: {client.get('name') or 'Unknown'}"]
    if client.get("business_location"):
        parts.append(f"Location: {client['business_location']}")
    icp = client.get("detected_icp")
    if isinstance(icp, dict):
        icp = icp.get("summary") or icp.get("description") or icp.get("raw_text")
    if isinstance(icp, str) and icp.strip():
        parts.append(f"Ideal customer: {icp.strip()[:400]}")
    return "\n".join(parts)


def _gap_prompt(client: dict, rows: list[dict]) -> str:
    lines = []
    for r in rows:
        kw = (r.get("keyword") or "").strip()
        if not kw:
            continue
        comp = r.get("competitor_domain") or "a competitor"
        lines.append(f"- {kw}  (ranks via {comp})")
    listing = "\n".join(lines)
    return (
        f"{_client_description(client)}\n\n"
        "Keywords a competitor ranks for that this business does not:\n"
        f"{listing}\n\n"
        "Return ONLY the keywords that are NOT a real content topic for this "
        "business — a specific company's brand/product name (including run-together "
        "product names), a login/portal/account/support lookup, a person/address/"
        "phone lookup, or an otherwise navigational query. KEEP genuine service or "
        "informational topics. If every keyword is a genuine topic, return an empty "
        "list."
    )


def llm_junk_keywords(rows: list[dict], client: dict, *, model: Optional[str] = None) -> set[str]:
    """One LLM call → the normalized subset of the provided gap keywords that are
    NOT content topics (brand/product/navigational). Best-effort: returns an empty
    set on no rows, no LLM key, disabled flag, or any failure. Guarded so it can
    only ever drop keywords that were actually in the input (never a hallucination)."""
    if not rows or not settings.domain_intel_gap_llm_filter:
        return set()
    have_key = bool(
        settings.anthropic_api_key or settings.openai_api_key or settings.gemini_api_key
    )
    if not have_key:
        return set()
    input_keywords = {_norm(r.get("keyword")) for r in rows if (r.get("keyword") or "").strip()}
    try:
        from services import report_llm

        result = report_llm.run_forced_tool_sync(
            provider="anthropic",
            model=model or settings.domain_intel_gap_filter_model,
            max_tokens=settings.domain_intel_gap_filter_max_tokens,
            system=_GAP_SYSTEM,
            user=_gap_prompt(client, rows),
            tool_name=_GAP_TOOL["name"],
            tool_description=_GAP_TOOL["description"],
            input_schema=_GAP_TOOL["input_schema"],
            log_tag="domain_intel_gap_filter",
        ) or {}
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.warning("gap_intel_filter.llm_failed", extra={"error": str(exc)})
        return set()
    drop: set[str] = set()
    for item in (result.get("not_content_keywords") or []):
        kw = _norm(item.get("keyword") if isinstance(item, dict) else item)
        if kw and kw in input_keywords:  # never drop a keyword we didn't ask about
            drop.add(kw)
    return drop


# ---------------------------------------------------------------------------
# Orchestration — deterministic then (best-effort) LLM. Impure only in the LLM
# call + the client-context read.
# ---------------------------------------------------------------------------
def _client_context(client_id: str) -> dict:
    try:
        rows = (
            get_supabase().table("clients")
            .select("name, business_location, detected_icp")
            .eq("id", client_id).limit(1).execute()
        ).data or []
        return rows[0] if rows else {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("gap_intel_filter.client_read_failed", extra={"client_id": client_id, "error": str(exc)})
        return {}


def apply_verdicts(
    rows: list[dict],
    matchers: list[set[str]],
    llm_drop: set[str],
    *,
    apply_deterministic: bool = True,
) -> tuple[list[dict], dict]:
    """Pure: drop rows the deterministic gate rejects, then rows the LLM flagged.
    Returns (kept_rows, report). ``llm_drop`` is the normalized keyword set from
    :func:`llm_junk_keywords` (empty when the LLM layer is off/unavailable);
    ``apply_deterministic=False`` skips the deterministic gate entirely (the
    navigational filter flag is off)."""
    kept: list[dict] = []
    reasons: list[dict] = []
    dropped_det = dropped_llm = 0
    for r in rows:
        kw = (r.get("keyword") or "").strip()
        if not kw:
            continue
        if apply_deterministic:
            det = deterministic_verdict(kw, matchers)
            if det != "keep":
                dropped_det += 1
                reasons.append({"keyword": kw, "layer": "deterministic", "reason": det})
                continue
        if _norm(kw) in llm_drop:
            dropped_llm += 1
            reasons.append({"keyword": kw, "layer": "llm", "reason": "brand_or_product"})
            continue
        kept.append(r)
    report = {
        "input": len(rows),
        "kept": len(kept),
        "dropped_deterministic": dropped_det,
        "dropped_llm": dropped_llm,
        "reasons": reasons[:50],
    }
    return kept, report


def filter_gap_rows(
    rows: list[dict],
    matchers: list[set[str]],
    client_id: str,
) -> tuple[list[dict], dict]:
    """Full gap-keyword quality filter: deterministic gate + best-effort LLM gate.
    Returns (kept_rows, report). The whole thing is best-effort — the deterministic
    gate always runs; the LLM gate degrades to a no-op on any failure."""
    nav_on = settings.domain_intel_navigational_filter
    llm_on = settings.domain_intel_gap_llm_filter
    if not nav_on and not llm_on:
        return rows, {"input": len(rows), "kept": len(rows), "dropped_deterministic": 0, "dropped_llm": 0, "reasons": []}
    # LLM only needs to judge the deterministic survivors, but classifying the whole
    # (already small, ≤ fetch pool) list in one call is simplest and costs the same.
    llm_drop = llm_junk_keywords(rows, _client_context(client_id)) if llm_on else set()
    return apply_verdicts(rows, matchers, llm_drop, apply_deterministic=nav_on)
