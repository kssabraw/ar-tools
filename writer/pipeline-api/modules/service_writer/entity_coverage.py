"""Entity-coverage enforcement for the service page (Option B).

The service brief benchmarks the required entity count against the MOST
AGGRESSIVE competitor (`ResearchBundle.entity_benchmark_target`). Until this
module the service writer only *suggested* covering the brief's `must_cover`
terms ("cover them naturally") — nothing measured the assembled page against
the benchmark. This adds the missing enforcement, mirroring the blog writer's
`term_coverage`:

- Count how many of the competitor-entity pool the page actually covers.
- If it falls below `floor × target`, regenerate the weakest content sections
  (fewest entities) with the missing entities named — ONE pass, warn-and-accept.
- Report the outcome as metadata; never abort generation.

The coverage computation is pure and deterministic (no LLM). The rewrite is
delegated to a caller-supplied `regen_section` coroutine so this module stays
free of the generation/model imports.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional, Sequence

logger = logging.getLogger(__name__)


@dataclass
class EntityCoverageStats:
    """Pure comparison of the competitor-entity pool vs the assembled page."""

    target: int = 0            # aggressive-competitor benchmark, clamped to pool size
    pool_size: int = 0
    covered: int = 0           # distinct pool entities present in the page
    needed: int = 0            # round(floor × target) — the rewrite trigger bar
    missing: list[str] = field(default_factory=list)
    rewrite_triggered: bool = False
    sections_rewritten: int = 0


def _entity_present(entity: str, text_lower: str) -> bool:
    """Multi-word entities match as a substring; single tokens use a word
    boundary so "ai" doesn't match inside "training" (same convention as the
    SIE / serp_signal_coverage substring checks)."""
    e = entity.strip().lower()
    if not e:
        return False
    if " " in e:
        return e in text_lower
    return re.search(rf"\b{re.escape(e)}\b", text_lower) is not None


def _dedupe(pool: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(p.strip().lower() for p in pool if p and p.strip()))


def compute_coverage(
    pool: Sequence[str], page_text: str, target: int, floor: float,
) -> EntityCoverageStats:
    """Measure distinct pool-entity coverage in the page text against the
    aggressive-competitor benchmark. `target` is clamped to the pool size (you
    cannot place more entities than exist), and the rewrite bar is
    round(floor × target)."""
    pool_terms = _dedupe(pool)
    text_lower = (page_text or "").lower()
    present = [e for e in pool_terms if _entity_present(e, text_lower)]
    present_set = set(present)
    missing = [e for e in pool_terms if e not in present_set]

    eff_target = min(int(target or 0), len(pool_terms))
    needed = int(round(floor * eff_target)) if eff_target > 0 else 0
    covered = len(present)
    return EntityCoverageStats(
        target=eff_target,
        pool_size=len(pool_terms),
        covered=covered,
        needed=needed,
        missing=missing,
        rewrite_triggered=(eff_target > 0 and covered < needed),
    )


def _page_text(sections: Sequence, block_text_fn: Callable) -> str:
    return "\n".join(
        f"{getattr(s, 'heading', '')}\n{block_text_fn(getattr(s, 'blocks', []) or [])}"
        for s in sections
    )


def _section_entity_count(section, pool_terms: list[str], block_text_fn: Callable) -> int:
    text = f"{getattr(section, 'heading', '')} {block_text_fn(getattr(section, 'blocks', []) or [])}".lower()
    return sum(1 for e in pool_terms if _entity_present(e, text))


async def enforce_entity_coverage(
    sections: Sequence,
    *,
    pool: Sequence[str],
    target: int,
    floor: float,
    max_sections: int,
    regen_section: Callable[[object, list[str]], Awaitable[Optional[list]]],
    block_text_fn: Callable,
) -> EntityCoverageStats:
    """Measure coverage across ALL sections; if short, regenerate the weakest
    CONTENT sections (type == "content") with the missing entities named, then
    re-measure. One rewrite pass. `regen_section(section, missing)` returns new
    blocks (or falsy to keep the section unchanged) and mutates nothing itself.
    """
    stats = compute_coverage(pool, _page_text(sections, block_text_fn), target, floor)
    if not stats.rewrite_triggered or not stats.missing:
        return stats

    pool_terms = _dedupe(pool)
    content = [s for s in sections if getattr(s, "type", "content") == "content"]
    # Weakest first: the sections carrying the fewest pool entities have the
    # most room to absorb the missing ones.
    ranked = sorted(content, key=lambda s: _section_entity_count(s, pool_terms, block_text_fn))

    rewritten = 0
    for section in ranked[: max(0, max_sections)]:
        # Re-measure before each rewrite and stop as soon as the coverage bar is
        # reached — so we only rewrite as many sections as needed and never
        # disturb sections that are already carrying their share of entities.
        current = compute_coverage(pool, _page_text(sections, block_text_fn), target, floor)
        if not current.rewrite_triggered:
            break
        try:
            # Feed the CURRENT missing list so each rewrite targets what's still short.
            new_blocks = await regen_section(section, list(current.missing))
        except Exception as exc:  # a rewrite failure must never abort the page
            logger.warning("service_writer.entity_rewrite_failed", extra={"error": str(exc)})
            new_blocks = None
        if new_blocks:
            section.blocks = new_blocks
            rewritten += 1

    final = compute_coverage(pool, _page_text(sections, block_text_fn), target, floor)
    final.rewrite_triggered = True
    final.sections_rewritten = rewritten
    return final
