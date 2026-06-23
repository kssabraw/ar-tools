"""Run cost estimation (PRD §8.1 cost matrix / §8.4 cost gate).

A pure, side-effect-free model that turns a run config (coverage mode, silo
count, deep-mine count, recursive fanout, metrics) into an estimated dollar cost.
The §8.4 approval gate (M9, §11.3) compares this estimate to the workspace soft
cap; the wizard surfaces it in the cost-confirmation step.

The per-component rates are derived from the §8.1 table, which is itself an
estimate at a representative config (5 silos, 3 deep-mined). They reconstruct the
table's subtotals within a few cents at that point and scale sensibly with silo /
deep-mine count, so an unusually large run (e.g. a 10-silo comprehensive run)
exceeds the cap while standard+metrics and comprehensive+metrics stay under it —
which is exactly the §8.4 intent. Update the rates after the first ~10 production
runs surface real numbers (per §8.1).
"""

from dataclasses import dataclass

# Flat per-run components ($), independent of silo / deep-mine count.
_SILO_DISCOVERY = 0.20            # grounding + demand sample + SERP structure
_DEDUP = 0.10                     # cross-topic dedup pass (1 call)
_ARCHITECTURE = 0.30             # site architecture generation

# Per-silo components ($/silo). Tuned to the §8.1 5-silo subtotals.
_EXPANSION_PER_SILO = 0.11        # 5 silos -> 0.55
_ORCHESTRATOR_PER_SILO = 0.10     # 5 silo-level planning calls -> 0.50
_METRICS_PER_SILO_STANDARD = 0.06   # 5 silos -> +0.30
_METRICS_PER_SILO_COMPREHENSIVE = 0.12  # 5 silos -> +0.60

# Per deep-mine unit ($/unit). A unit is the always-mined seed plus each gated
# silo, so deep-mine cost scales with how many silos the user gated.
_MINING_PER_UNIT_STANDARD = 0.15
_MINING_PER_UNIT_COMPREHENSIVE = 0.30

# Mode-flat components ($) keyed by coverage mode.
_AUTOCOMPLETE = {"standard": 0.30, "comprehensive": 0.60}
_RELEVANCE = {"standard": 0.05, "comprehensive": 0.10}
_ORCHESTRATOR_SERP = {"standard": 0.30, "comprehensive": 0.50}

# Recursive fanout multiplier on the whole base run (§7.7 / §8.1: ~5x-8x). The
# low end is used for the headline estimate (conservative against under-quoting is
# moot here — recursive always trips the gate regardless of the number).
_RECURSIVE_MULTIPLIER = 5.0


@dataclass(frozen=True)
class CostEstimate:
    total_usd: float
    breakdown: dict[str, float]
    recursive_multiplier: float | None  # None when not a recursive run


def estimate_cost(
    *,
    coverage_mode: str,
    silo_count: int,
    deep_mine_count: int,
    recursive_fanout: bool = False,
    enrich_with_metrics: bool = False,
) -> CostEstimate:
    """Estimate the dollar cost of a run from its config (PRD §8.1).

    `deep_mine_count` is the number of *additional* silos gated for competitor
    mining; the seed is always mined and is added on top. `silo_count` is the
    number of finalized silos. Unknown coverage modes fall back to standard rates.
    """
    mode = coverage_mode if coverage_mode in _AUTOCOMPLETE else "standard"
    silos = max(silo_count, 1)
    # Seed is always mined; gated silos add to it. Clamp negatives defensively.
    mining_units = 1 + max(deep_mine_count, 0)

    mining_rate = (
        _MINING_PER_UNIT_COMPREHENSIVE if mode == "comprehensive"
        else _MINING_PER_UNIT_STANDARD
    )
    breakdown: dict[str, float] = {
        "silo_discovery": _SILO_DISCOVERY,
        "expansion": round(_EXPANSION_PER_SILO * silos, 4),
        "competitor_mining": round(mining_rate * mining_units, 4),
        "autocomplete": _AUTOCOMPLETE[mode],
        "relevance_gate": _RELEVANCE[mode],
        "orchestrator_serp": _ORCHESTRATOR_SERP[mode],
        "article_orchestrator": round(_ORCHESTRATOR_PER_SILO * silos, 4),
        "cross_topic_dedup": _DEDUP,
        "site_architecture": _ARCHITECTURE,
    }
    if enrich_with_metrics:
        metrics_rate = (
            _METRICS_PER_SILO_COMPREHENSIVE if mode == "comprehensive"
            else _METRICS_PER_SILO_STANDARD
        )
        breakdown["metrics_enrichment"] = round(metrics_rate * silos, 4)

    base = round(sum(breakdown.values()), 2)
    if recursive_fanout:
        total = round(base * _RECURSIVE_MULTIPLIER, 2)
        return CostEstimate(total, breakdown, _RECURSIVE_MULTIPLIER)
    return CostEstimate(base, breakdown, None)


def requires_approval(
    *, estimated_cost_usd: float, soft_cap_usd: float, recursive_fanout: bool
) -> tuple[bool, list[str]]:
    """Approval-gate decision for a VA run (PRD §8.4 / §11.3): approval is needed
    when the estimate exceeds the soft cap OR recursive fanout was requested.
    Returns (needs_approval, human-readable trigger reasons)."""
    triggers: list[str] = []
    if recursive_fanout:
        triggers.append("recursive_fanout")
    if estimated_cost_usd > soft_cap_usd:
        triggers.append("over_soft_cap")
    return (bool(triggers), triggers)
