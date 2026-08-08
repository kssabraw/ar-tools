"""Keyword Research — audience-fit filter.

The relevance gate answers "is this keyword on-topic?" but not "would our BUYER
search it?" — and those differ. For a B2B third-party claims administrator whose
ICP is an "Insurance Carrier Claims Operations Manager", keywords like
"insurance adjuster salary", "claims adjuster jobs", "how to become an adjuster"
are 100% on-topic and 0% useful: they target job-seekers, not the carriers who
hire a TPA. On a live BSA Claims run 55% of the keywords were this job-seeker /
career universe, which is why the results "weren't great for blog posts".

Two layers, mirroring the module's hybrid philosophy (cheap deterministic first,
LLM only where judgement is needed):

  * a DETERMINISTIC job-seeker guard — a curated employment/career vocabulary
    ("salary", "jobs", "career", "how to become", "resume", "hiring", …) that is
    near-universally noise for content SEO (a business doesn't publish blog posts
    to rank for recruiting queries). Pure, unit-tested.
  * an ICP-GROUNDED off-audience pass — one LLM call that, given the client's ICP,
    returns the CLIENT-SPECIFIC wrong-audience vocabulary the universal list can't
    know (for BSA: "public adjuster", "license", "file a claim" — consumer /
    policyholder / licensing intent). The terms are then applied deterministically
    so the drop is explainable. Best-effort — no ICP / no LLM key → this layer is
    skipped and only the universal guard runs.

Every kept keyword is tagged with ``audience_fit`` ('buyer' | 'job_seeker' |
'off_audience') so the drop is transparent and tunable.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from config import settings
from services import keyword_research, keyword_research_seeds

logger = logging.getLogger(__name__)

# Universal job-seeker / employment vocabulary — content SEO never targets these
# (ranking for "adjuster salary" attracts applicants, not customers). Matched as
# whole words / phrases against the normalized keyword. Deliberately the
# EMPLOYMENT senses only; ambiguous education/licensing words (course, license,
# certification) are left to the ICP pass, since for some clients those ARE the
# product.
_JOB_SEEKER_TERMS = (
    "salary", "salaries", "wage", "wages", "paycheck", "paystub",
    "jobs", "job description", "job outlook", "job openings", "job listings",
    "career", "careers", "hiring", "now hiring", "recruiter", "recruitment",
    "resume", "cover letter", "interview questions",
    "how to become", "become a", "become an", "how do i become", "how do you become",
    "entry level", "entry-level", "apprentice", "apprenticeship",
    "internship", "work from home", "remote jobs",
)


def _phrase_regex(terms) -> re.Pattern:
    """A word-boundary alternation matching any of ``terms`` (phrases allowed)."""
    parts = sorted((re.escape(t) for t in terms), key=len, reverse=True)
    return re.compile(r"\b(?:" + "|".join(parts) + r")\b", re.I)


_JOB_SEEKER_RE = _phrase_regex(_JOB_SEEKER_TERMS)


# ---------------------------------------------------------------------------
# Pure helpers (no I/O) — independently unit-tested.
# ---------------------------------------------------------------------------
def is_job_seeker(keyword: Optional[str]) -> bool:
    """Whether a keyword reads as a job-seeker / career / recruiting query — the
    universal wrong-audience class for content SEO. Pure."""
    return bool(_JOB_SEEKER_RE.search(keyword_research.normalize_keyword(keyword)))


def matches_any(keyword: Optional[str], pattern: Optional[re.Pattern]) -> bool:
    """Whether a keyword contains any term in a compiled off-audience pattern. Pure."""
    if pattern is None:
        return False
    return bool(pattern.search(keyword_research.normalize_keyword(keyword)))


def classify_audience(
    keyword: Optional[str], off_audience_re: Optional[re.Pattern]
) -> str:
    """Audience-fit tag for a keyword: 'job_seeker' (universal guard) >
    'off_audience' (ICP-specific terms) > 'buyer'. Pure."""
    if is_job_seeker(keyword):
        return "job_seeker"
    if matches_any(keyword, off_audience_re):
        return "off_audience"
    return "buyer"


def apply_audience(
    rows: list[dict],
    off_audience_terms: Optional[list[str]] = None,
    *,
    drop: bool = True,
) -> tuple[list[dict], dict]:
    """Tag every row with ``audience_fit`` and (when ``drop``) remove the
    non-buyer rows. Returns (kept_rows, report). ``report`` =
    {gate, input, kept, dropped_job_seeker, dropped_off_audience,
    off_audience_terms}. Pure — the LLM term-fetch is done by the caller."""
    off_re = _phrase_regex(off_audience_terms) if off_audience_terms else None
    kept: list[dict] = []
    dropped_js = dropped_oa = 0
    for r in rows:
        fit = classify_audience(r.get("keyword"), off_re)
        r = {**r, "audience_fit": fit}
        if fit == "buyer" or not drop:
            kept.append(r)
        elif fit == "job_seeker":
            dropped_js += 1
        else:
            dropped_oa += 1
    report = {
        "gate": "audience" if (dropped_js or dropped_oa) else "none",
        "input": len(rows), "kept": len(kept),
        "dropped_job_seeker": dropped_js, "dropped_off_audience": dropped_oa,
        "off_audience_terms": list(off_audience_terms or []),
    }
    return kept, report


# ---------------------------------------------------------------------------
# ICP off-audience vocabulary (I/O via the shared report_llm transport).
# ---------------------------------------------------------------------------
_ICP_SYSTEM = (
    "You are an SEO audience strategist. Given a business's ideal customer (ICP) "
    "and a sample of keywords from a research run, identify the WRONG-AUDIENCE "
    "terms — words or short phrases that mark a keyword as targeting someone the "
    "business does NOT sell to (e.g. job-seekers, students, DIY consumers, or "
    "policyholders for a B2B insurance-services company). Be precise: only return "
    "terms that clearly signal the wrong audience for THIS business."
)
_ICP_TOOL = {
    "name": "emit_audience",
    "description": "Return wrong-audience terms for this business's buyer.",
    "input_schema": {
        "type": "object",
        "properties": {
            "off_audience_terms": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Words / short phrases (lowercase) that mark a keyword "
                               "as targeting the WRONG audience for this business — the "
                               "buyer would never search them. Omit generic job-seeker "
                               "words (salary, jobs, career) which are already handled.",
            },
        },
        "required": ["off_audience_terms"],
    },
}


def _icp_prompt(icp_text: str, sample_keywords: list[str]) -> str:
    sample = "\n".join(f"- {k}" for k in sample_keywords[:60])
    return (
        f"Ideal customer (ICP) for this business:\n{icp_text}\n\n"
        f"A keyword research run produced these (sample):\n{sample}\n\n"
        "Return the WRONG-AUDIENCE terms — short words/phrases that mark a keyword "
        "as targeting someone this business does NOT sell to (students, DIY "
        "consumers, job-seekers beyond the obvious salary/jobs words, licensing/"
        "certification seekers, policyholders if the business sells to insurers, "
        "etc.). Only terms you're confident signal the wrong audience. If every "
        "sample looks on-audience, return an empty list."
    )


def icp_off_audience_terms(client: dict, sample_keywords: list[str]) -> list[str]:
    """One LLM call → the client-specific wrong-audience vocabulary, grounded on the
    ICP. Best-effort: returns [] when no ICP text, no LLM key, or the call fails."""
    from services import icp_service

    icp_text = icp_service.resolve_icp_text(client)
    if not icp_text or not settings.keyword_research_audience_icp:
        return []
    have_key = bool(
        settings.anthropic_api_key or settings.openai_api_key or settings.gemini_api_key
    )
    if not have_key:
        return []
    try:
        from services import report_llm

        result = report_llm.run_forced_tool_sync(
            provider="anthropic",
            model=settings.keyword_research_audience_model,
            max_tokens=settings.keyword_research_audience_max_tokens,
            system=_ICP_SYSTEM,
            user=_icp_prompt(icp_text, sample_keywords),
            tool_name=_ICP_TOOL["name"],
            tool_description=_ICP_TOOL["description"],
            input_schema=_ICP_TOOL["input_schema"],
            log_tag="keyword_research_audience_icp",
        ) or {}
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.warning("keyword_research_audience.icp_failed", extra={"error": str(exc)})
        return []
    terms = []
    seen: set[str] = set()
    for t in (result.get("off_audience_terms") or []):
        s = re.sub(r"\s+", " ", str(t or "").strip().lower())
        # Guard: never accept a term that would nuke on-topic keywords — drop any
        # term that appears in the client's own seeds' significant tokens.
        if s and len(s) >= 3 and s not in seen:
            seen.add(s)
            terms.append(s)
    return terms[: settings.keyword_research_audience_max_terms]


def guard_off_terms(off_terms: list[str], seeds: list[str]) -> list[str]:
    """Drop any ICP off-audience term that shares a significant token with the
    seeds — such a term would filter the run's own core topic (a mis-returned
    "claims"/"adjuster" would nuke everything). Pure."""
    seed_toks: set[str] = set()
    for s in seeds or []:
        seed_toks |= keyword_research.token_set(s)
    if not seed_toks:
        return list(off_terms or [])
    safe: list[str] = []
    for t in off_terms or []:
        if not (keyword_research.token_set(t) & seed_toks):
            safe.append(t)
    return safe


def filter_by_audience(
    rows: list[dict], client: dict, seeds: list[str]
) -> tuple[list[dict], dict]:
    """Full audience-fit filter: the universal job-seeker guard + the ICP-grounded
    off-audience terms (guarded so an ICP term can't collide with a seed word).
    Returns (kept_rows_tagged, report). Best-effort — the ICP layer degrades to the
    universal guard alone; the whole filter is skipped when disabled by config."""
    if not settings.keyword_research_audience_filter:
        return rows, {"gate": "off"}
    # Sample the highest-volume keywords for the ICP pass (representative + cheap).
    sample = [r.get("keyword") for r in sorted(
        rows, key=lambda x: (x.get("volume") or 0), reverse=True)][:60]
    off_terms = guard_off_terms(
        icp_off_audience_terms(client, [k for k in sample if k]), seeds)
    return apply_audience(rows, off_terms, drop=True)
