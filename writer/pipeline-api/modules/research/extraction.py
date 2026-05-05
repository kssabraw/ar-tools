"""Step 5b/5c — Claim extraction (LLM) + verification (deterministic).

Extraction: single Claude call per winning candidate. Asks for up to 5
verbatim claims. 25-second timeout, no retry on extraction (per PRD §5d
fall through to next candidate instead).

Verification: deterministic three-stage check
1. Verbatim substring match (case-insensitive, whitespace-normalized)
2. Sliding-window fuzzy match (Levenshtein ratio >= 0.90)
3. Number integrity: every numeric token in the claim must appear in the
   source text exactly. Numbers that don't match cause rejection regardless
   of fuzzy score.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Literal, Optional

from modules.brief.llm import claude_json

from .recency import _parse_date  # for token typing only

logger = logging.getLogger(__name__)

EXTRACTION_TIMEOUT = 25.0
SOURCE_TEXT_CHAR_LIMIT = 24_000  # ~6000 tokens
NUMERIC_TOKEN_RE = re.compile(
    r"\$?\d[\d,]*\.?\d*%?"  # numbers, percentages, currency
)


@dataclass
class ExtractedClaim:
    claim_text: str
    relevance_score: float
    extraction_method: Literal["verbatim_extraction", "fallback_stub"] = "verbatim_extraction"
    verification_method: Literal["verbatim_match", "fuzzy_match", "none"] = "verbatim_match"


CLAIM_EXTRACTION_PROMPT = """You are extracting specific, quotable factual claims from a source document to support a blog post section.

Blog post keyword: {keyword}
Section heading: {heading_text}

From the source text below, extract up to 5 specific, quotable claims or data points that:
- Are factual and specific (statistics, percentages, named study findings, official regulatory guidance, or direct expert quotes with attribution)
- Directly support the topic of the section heading above
- Are self-contained - understandable without the surrounding paragraph
- Are not editorial opinion, vague generalizations, or unquantified assertions

CRITICAL: Use the source's exact words and exact numbers. Do not paraphrase. Do not round. Do not infer values not stated in the text. If a claim cannot be quoted verbatim, do not include it.

Return a JSON array of objects only, with no preamble or markdown formatting:
[
  {{
    "claim_text": "<the exact quoted text from the source - verbatim, including numbers>",
    "relevance_score": <float 0.0-1.0>
  }}
]

Source text:
{source_text}"""


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _verbatim_match(claim: str, source: str) -> bool:
    return _normalize_whitespace(claim) in _normalize_whitespace(source)


def _levenshtein_ratio(a: str, b: str) -> float:
    """Returns 0.0-1.0 similarity (1.0 = identical)."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    n, m = len(a), len(b)
    if n > m:
        a, b = b, a
        n, m = m, n
    current = list(range(n + 1))
    for i in range(1, m + 1):
        previous, current = current, [i] + [0] * n
        for j in range(1, n + 1):
            add = previous[j] + 1
            delete = current[j - 1] + 1
            change = previous[j - 1] + (0 if a[j - 1] == b[i - 1] else 1)
            current[j] = min(add, delete, change)
    distance = current[n]
    max_len = max(len(a), len(b))
    return 1.0 - (distance / max_len) if max_len else 1.0


def _fuzzy_match(claim: str, source: str, threshold: float = 0.90) -> bool:
    """Sliding-window fuzzy: scan windows of len(claim) across source."""
    claim_n = _normalize_whitespace(claim)
    source_n = _normalize_whitespace(source)
    if not claim_n or not source_n:
        return False
    cl = len(claim_n)
    if cl > len(source_n):
        return _levenshtein_ratio(claim_n, source_n) >= threshold
    step = max(1, cl // 4)
    for i in range(0, len(source_n) - cl + 1, step):
        window = source_n[i : i + cl]
        if _levenshtein_ratio(claim_n, window) >= threshold:
            return True
    return False


def _extract_numeric_tokens(text: str) -> list[str]:
    return NUMERIC_TOKEN_RE.findall(text)


def _verify_numeric_integrity(claim: str, source: str) -> bool:
    """Every numeric token in the claim must appear in the source verbatim."""
    claim_numbers = _extract_numeric_tokens(claim)
    if not claim_numbers:
        return True  # No numbers to check
    source_numbers = set(_extract_numeric_tokens(source))
    return all(n in source_numbers for n in claim_numbers)


def verify_claim(claim_text: str, source_text: str) -> Optional[str]:
    """Returns verification_method if claim passes, None if it fails."""
    if not _verify_numeric_integrity(claim_text, source_text):
        return None
    if _verbatim_match(claim_text, source_text):
        return "verbatim_match"
    if _fuzzy_match(claim_text, source_text):
        return "fuzzy_match"
    return None


async def extract_claims(
    keyword: str,
    heading_text: str,
    source_text: str,
) -> list[ExtractedClaim]:
    """Run LLM claim extraction + verification. Returns verified claims."""
    if not source_text or not source_text.strip():
        return []

    truncated = source_text[:SOURCE_TEXT_CHAR_LIMIT]
    prompt = CLAIM_EXTRACTION_PROMPT.format(
        keyword=keyword,
        heading_text=heading_text,
        source_text=truncated,
    )

    try:
        result = await asyncio.wait_for(
            claude_json(
                system="You extract verbatim factual claims from source text.",
                user=prompt,
                max_tokens=1500,
                temperature=0.1,
            ),
            timeout=EXTRACTION_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning("Claim extraction timeout")
        return []
    except Exception as exc:
        logger.warning("Claim extraction failed: %s", exc)
        return []

    raw_claims = []
    if isinstance(result, list):
        raw_claims = result
    elif isinstance(result, dict):
        for key in ("claims", "items"):
            if isinstance(result.get(key), list):
                raw_claims = result[key]
                break

    verified: list[ExtractedClaim] = []
    for entry in raw_claims:
        if not isinstance(entry, dict):
            continue
        claim_text = entry.get("claim_text") or entry.get("text") or ""
        if not isinstance(claim_text, str) or not claim_text.strip():
            continue
        try:
            relevance = float(entry.get("relevance_score", 0.0))
        except (TypeError, ValueError):
            relevance = 0.0
        if relevance < 0.50:
            continue
        method = verify_claim(claim_text, source_text)
        if method is None:
            logger.info("Claim verification failed for: %s", claim_text[:60])
            continue
        verified.append(ExtractedClaim(
            claim_text=claim_text.strip(),
            relevance_score=round(relevance, 3),
            extraction_method="verbatim_extraction",
            verification_method=method,
        ))

    return verified[:5]


def fallback_stub(title: str, meta_description: str) -> ExtractedClaim:
    """Per PRD §5d — when no candidates yield verified claims, use the
    rank-1 candidate's title + meta as a stub claim (relevance 0.30)."""
    text = (title or "").strip()
    if meta_description:
        text = f"{text} - {meta_description.strip()}" if text else meta_description.strip()
    return ExtractedClaim(
        claim_text=text or "[no claim available]",
        relevance_score=0.30,
        extraction_method="fallback_stub",
        verification_method="none",
    )
