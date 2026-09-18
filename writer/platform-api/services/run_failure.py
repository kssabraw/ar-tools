"""Plain-English explanations for terminal run failures — pure, unit-tested.

The orchestrator records a terse ``StageError`` cause (e.g.
``module_error: HTTP 500: {"detail":"internal_error"}``) that is precise but
opaque to a non-engineer. This turns (stage, cause, retry_count) into a human
summary of WHAT failed, WHY, and what to do next, for the ``run_failed``
notification — so a stuck/failed article tells the person who started it what
went wrong instead of an internal code.

No I/O; the explanation is derived only from the stage + cause strings.
"""

from __future__ import annotations

from typing import Optional

from services import run_retry

# Friendly names for the internal pipeline stage keys.
_STAGE_LABELS = {
    "brief": "content brief",
    "sie": "term & entity analysis (SIE)",
    "research": "research & citations",
    "writer": "article writing",
    "sources_cited": "sources & citations",
    "service_brief": "service-page brief",
    "service_writer": "service-page writing",
    "service_score": "service-page scoring",
    "recovery": "run recovery",
    "unknown": "content pipeline",
}


def stage_label(stage: Optional[str]) -> str:
    """A human name for an internal stage key. Pure."""
    key = (stage or "").lower()
    return _STAGE_LABELS.get(key, key or "content pipeline")


# (marker, why-phrase) — first case-insensitive substring match wins. The phrase
# completes the sentence "The <stage> step failed because <phrase>."
_REASON_RULES: list[tuple[str, str]] = [
    ("serp_no_results",
     "the search-results provider returned no usable competitor results for this keyword"),
    ("serp_failed",
     "the search-results (SERP) provider failed while gathering competitor data"),
    ("module_timeout",
     "the step took too long and timed out — usually a slow upstream data provider"),
    ("module_unavailable",
     "the service was briefly unreachable (for example during a deploy)"),
    ("http 5",
     "it hit an internal server error while processing — usually a temporary problem with an "
     "upstream provider (the page scraper or SERP data), not something wrong with your keyword"),
    ("http 4",
     "a request was rejected as invalid (a data or validation problem), which is a bug rather "
     "than a passing hiccup"),
    ("schema",
     "a module returned data in an unexpected shape (a version/schema mismatch), which is a bug"),
    ("cancel",
     "the run was cancelled"),
]


def failure_reason(cause: Optional[str]) -> str:
    """The why-phrase for a StageError cause. Pure."""
    text = (cause or "").lower()
    for marker, why in _REASON_RULES:
        if marker in text:
            return why
    return "of an unexpected error"


def explain_failure(
    stage: Optional[str], cause: Optional[str], retry_count: int = 0
) -> str:
    """A one-paragraph plain-English summary of a terminal run failure: what step
    failed, why, and what to do. Pure — unit-tested.

    The transient-vs-permanent judgement reuses ``run_retry.is_transient_stage_error``
    so the guidance stays consistent with the auto-retry policy: a transient class
    that STILL failed after N retries is called out as a likely persistent problem
    (which is exactly what a deterministic bug behind an HTTP 500 looks like)."""
    label = stage_label(stage)
    why = failure_reason(cause)
    transient = run_retry.is_transient_stage_error(cause or "")
    if transient and retry_count:
        tail = (
            f" It was retried automatically {retry_count} "
            f"time{'s' if retry_count != 1 else ''} and kept failing, which points to a "
            "persistent problem rather than a passing blip — please report it if re-running "
            "doesn't clear it."
        )
    elif transient:
        tail = " Re-running often clears a one-off upstream blip."
    else:
        tail = " Re-running won't help until the underlying issue is fixed — please report it."
    return f"The {label} step failed because {why}.{tail}"
