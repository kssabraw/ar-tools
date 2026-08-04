"""The I-004 spike: which place-name granularity should AI prompts use?

PRD §16a.2. The assumption under test is that the place name in an AI prompt is at the right
granularity — specific enough that a small local operator could plausibly appear, general enough
that the model recognises the place at all.

Three failure modes, and the third is the dangerous one:

    too coarse ("Los Angeles")     metro-wide operators. A two-truck shop was never going to
                                   appear, so "you are not in ChatGPT" is trivially true and easy
                                   to dismiss.
    right ("Woodland Hills")       businesses at the prospect's scale. Absence is meaningful.
    too fine (unrecognised)        the model SILENTLY falls back to the metro. You get the coarse
                                   answer while believing you asked a specific question.

The third is why this is measured rather than assumed. A wrong answer that looks like a right one
is the same failure class as I-059 (a 404 reading as "no reviews") and I-064 (a documented
explanation believed instead of the live config). The whole spike exists to avoid paying for a
signal that means something other than what it appears to mean.

WHAT THIS MODULE DOES AND DOES NOT DECIDE.

It gathers evidence and computes overlap. It does NOT pick the granularity — that is a human
decision recorded in `ai_region.name_level`, because the trade-off (specificity vs recognition)
is a judgement about how the pitch will be received, not an arithmetic result. The verdict
helpers below say what the samples show; a person says what to do about it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

# One keyword, three granularities, three samples each, one engine — exactly PRD §16a.2.
# Not tunable by accident: widening this is a decision about spend and about what the comparison
# means, so it belongs in a code change with a reason attached.
SAMPLES_PER_LEVEL = 3

_PROMPT = (
    "Name the best {keyword}s in {place}. "
    "Reply with ONLY a JSON array of business names, no commentary. "
    "If you do not recognise the place, still answer for the closest place you do recognise."
)


@dataclass(frozen=True)
class LevelSample:
    """One engine answer at one granularity."""

    level: str          # 'metro' | 'suburb' | 'neighbourhood'
    place: str
    sample_index: int
    businesses: tuple[str, ...]
    raw: str = ""
    error: str = ""


@dataclass
class GranularityReport:
    keyword: str
    levels: dict[str, str]                       # level -> place name asked about
    samples: list[LevelSample] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def build_prompt(keyword: str, place: str) -> str:
    """The prompt is deliberately identical across levels except for the place name.

    If the wording varied by level, a difference in the answers could be the wording rather than
    the geography, and the whole comparison would be uninterpretable.
    """
    return _PROMPT.format(keyword=keyword, place=place)


def parse_business_names(raw: str) -> tuple[str, ...]:
    """Pull the business names out of an engine reply.

    Tolerant on purpose: models wrap JSON in prose or fences no matter how firmly the prompt asks
    them not to. Returns an empty tuple when nothing parses — the caller records that as a sample
    that yielded nothing, which is different from a sample that errored, and both are different
    from a sample that returned names.
    """
    if not raw:
        return ()

    # A fenced or bare JSON array anywhere in the reply.
    match = re.search(r"\[.*?\]", raw, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            names = [str(x).strip() for x in parsed if str(x).strip()]
            if names:
                return tuple(names)

    # Fall back to numbered or bulleted lines.
    names = []
    for line in raw.splitlines():
        line = line.strip()
        stripped = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line)
        if stripped and stripped != line:
            names.append(stripped.strip("*_ "))
    return tuple(names)


def normalize(name: str) -> str:
    """Compare business names loosely — punctuation and case are noise here, not signal."""
    return re.sub(r"[^a-z0-9 ]", "", name.lower()).strip()


def overlap(a: "tuple[str, ...] | list[str]", b: "tuple[str, ...] | list[str]") -> float:
    """Jaccard overlap of two name sets, 0.0–1.0. Empty on either side returns 0.0.

    This is the measurement the spike turns on: if the metro answer and the suburb answer name
    the same businesses, the suburb name is not actually narrowing anything and the model is
    almost certainly answering the metro question.
    """
    sa = {normalize(x) for x in a if normalize(x)}
    sb = {normalize(x) for x in b if normalize(x)}
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def names_at_level(report: GranularityReport, level: str) -> tuple[str, ...]:
    """Every business named across that level's samples, deduped, order preserved."""
    seen: set[str] = set()
    out: list[str] = []
    for s in report.samples:
        if s.level != level:
            continue
        for name in s.businesses:
            key = normalize(name)
            if key and key not in seen:
                seen.add(key)
                out.append(name)
    return tuple(out)


def level_stability(report: GranularityReport, level: str) -> float:
    """Mean pairwise overlap BETWEEN samples at the same level.

    Low stability means the engine is not answering consistently, which matters because it bounds
    how much a cross-level difference can be trusted: if repeated asks of the same place disagree
    as much as different places do, the cross-level comparison is measuring noise.
    """
    sets = [s.businesses for s in report.samples if s.level == level and s.businesses]
    if len(sets) < 2:
        return 0.0
    pairs = [
        overlap(sets[i], sets[j])
        for i in range(len(sets))
        for j in range(i + 1, len(sets))
    ]
    return sum(pairs) / len(pairs) if pairs else 0.0


def summarize(report: GranularityReport, fallback_threshold: float = 0.7) -> dict[str, Any]:
    """What the samples show. Deliberately NOT a recommendation.

    `fallback_threshold` is the overlap above which a finer level is treated as having collapsed
    into the coarser one — the silent-fallback failure. 0.7 is a starting point, not a measured
    constant, and it is a parameter rather than a literal so that the number used is visible in
    the output and can be revised without editing logic.
    """
    metro = names_at_level(report, "metro")
    suburb = names_at_level(report, "suburb")
    hood = names_at_level(report, "neighbourhood")

    suburb_vs_metro = overlap(suburb, metro)
    hood_vs_metro = overlap(hood, metro)
    hood_vs_suburb = overlap(hood, suburb)

    errors = [s for s in report.samples if s.error]
    empty = [s for s in report.samples if not s.error and not s.businesses]

    findings: list[str] = []
    if suburb_vs_metro >= fallback_threshold:
        findings.append(
            f"suburb answers overlap metro answers {suburb_vs_metro:.0%} — the suburb name may "
            "not be narrowing anything"
        )
    if hood_vs_metro >= fallback_threshold:
        findings.append(
            f"neighbourhood answers overlap metro answers {hood_vs_metro:.0%} — LIKELY SILENT "
            "FALLBACK to the metro, which is the failure this spike exists to catch"
        )
    if not findings:
        findings.append(
            "each level named a materially different set of businesses — the names are "
            "discriminating as intended"
        )

    return {
        "keyword": report.keyword,
        "levels": report.levels,
        "samples_per_level": SAMPLES_PER_LEVEL,
        "distinct_businesses": {
            "metro": len(metro),
            "suburb": len(suburb),
            "neighbourhood": len(hood),
        },
        "overlap": {
            "suburb_vs_metro": round(suburb_vs_metro, 3),
            "neighbourhood_vs_metro": round(hood_vs_metro, 3),
            "neighbourhood_vs_suburb": round(hood_vs_suburb, 3),
        },
        "within_level_stability": {
            level: round(level_stability(report, level), 3)
            for level in ("metro", "suburb", "neighbourhood")
        },
        "fallback_threshold": fallback_threshold,
        "findings": findings,
        "errors": len(errors),
        "empty_samples": len(empty),
        "names": {"metro": list(metro), "suburb": list(suburb), "neighbourhood": list(hood)},
        # Stated in the output, not just in a docstring, because whoever reads this JSON months
        # from now is the person most likely to mistake it for a decision.
        "note": (
            "Evidence only. The granularity to use is a human decision recorded in "
            "ai_region.name_level — specificity versus recognition is a judgement about how the "
            "pitch lands, not an arithmetic result."
        ),
    }


# --- the engine call -------------------------------------------------------------------------
#
# One engine, per §16a.2. OpenAI, because the question under test is a CONSUMER one ("who is the
# best plumber in X") and ChatGPT is the closest analogue to how a customer would actually ask.
#
# The key arrives as OUTREACH_OPENAI_API_KEY, a Railway reference to ${{PLATFORM.OPENAI_API_KEY}},
# so the secret never leaves the platform service and a rotation propagates — the same pattern as
# the DataForSEO credentials.

import httpx  # noqa: E402

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
_TIMEOUT = 60.0


class AiGranularityError(RuntimeError):
    """A failure talking to the engine. Never returned as an empty answer.

    An empty answer and a failed call mean different things here — one says the model named
    nothing, the other says we did not ask successfully — and collapsing them would let an outage
    read as "the model does not know this place", which is a conclusion the spike is supposed to
    reach only from evidence.
    """


def missing_openai_vars(settings) -> list[str]:  # noqa: ANN001
    return [] if getattr(settings, "openai_api_key", "") else ["OUTREACH_OPENAI_API_KEY"]


async def ask_engine(api_key: str, model: str, prompt: str) -> str:
    """One question, one answer, raw text back. Raises rather than returning empty on failure."""
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        # Temperature 0 so repeat samples measure the model's actual stability rather than
        # sampling noise we introduced ourselves.
        "temperature": 0,
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(
                OPENAI_CHAT_URL,
                json=payload,
                headers={"Authorization": f"Bearer {api_key}"},
            )
            response.raise_for_status()
            body = response.json()
    except httpx.HTTPStatusError as exc:
        raise AiGranularityError(
            f"HTTP {exc.response.status_code} from {exc.request.url}"
        ) from exc
    except httpx.HTTPError as exc:
        raise AiGranularityError(f"transport error: {exc}") from exc

    choices = body.get("choices") or []
    if not choices:
        raise AiGranularityError("response carried no choices")
    return (choices[0].get("message") or {}).get("content") or ""


async def run_spike(
    settings,  # noqa: ANN001
    keyword: str,
    metro: str,
    suburb: str,
    neighbourhood: str,
    model: str,
) -> GranularityReport:
    """The full §16a.2 procedure: three granularities × SAMPLES_PER_LEVEL, one engine."""
    missing = missing_openai_vars(settings)
    if missing:
        raise AiGranularityError(f"missing credentials: {', '.join(missing)}")

    levels = {"metro": metro, "suburb": suburb, "neighbourhood": neighbourhood}
    report = GranularityReport(keyword=keyword, levels=levels)

    for level, place in levels.items():
        prompt = build_prompt(keyword, place)
        for i in range(SAMPLES_PER_LEVEL):
            try:
                raw = await ask_engine(settings.openai_api_key, model, prompt)
                report.samples.append(
                    LevelSample(
                        level=level,
                        place=place,
                        sample_index=i,
                        businesses=parse_business_names(raw),
                        raw=raw[:2000],
                    )
                )
            except AiGranularityError as exc:
                # Recorded, not raised: one failed sample should not discard the eight that
                # worked, and `summarize` reports the error count so a degraded run is visible
                # rather than quietly thinner.
                report.samples.append(
                    LevelSample(
                        level=level, place=place, sample_index=i, businesses=(), error=str(exc)
                    )
                )
    return report
