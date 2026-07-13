"""LeadOff peer-cohort field-strength — a winnability signal that judges a
market's GBP competitive field against COMPARABLE cities, not in absolute terms.

The base rankability reads the field absolutely: a small, lower-income town with
a thin review field scores as beatable regardless of whether that thinness is
normal for its class or unusually soft. This layer benchmarks each market's
field-strength (`rev_win` — reviews to beat the #3 incumbent) against a cohort
of cities of similar SIZE and HOUSEHOLD INCOME serving the SAME category, so we
can tell a genuinely soft field from one that only looks soft because the market
is small or poor — and, conversely, flag a field that is *harder than it looks*
for its class.

Signal convention (matches leadoff_scoring winnability): a value in [-1, 1]
where POSITIVE = this market's field is weaker than its peers → easier to win,
NEGATIVE = stronger than its peers → harder.

Cohort key = (category_id, size band, income band). A fallback ladder widens
the cohort — drop the income band, then the size band — until it holds enough
peers for a stable median; below the floor at every level the signal is None
(contributes 0 to the grade — graceful). A market missing household income
still earns a size-only cohort signal rather than nothing.

Pure (no I/O). Unit-tested in tests/test_leadoff_peer_cohort.py.
"""
from __future__ import annotations

from bisect import bisect_right
from typing import Any, Optional


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def median(vals: list[float]) -> Optional[float]:
    vs = sorted(v for v in vals if v is not None)
    if not vs:
        return None
    n = len(vs)
    return vs[n // 2] if n % 2 else (vs[n // 2 - 1] + vs[n // 2]) / 2


def quantile_edges(values: list[float], n: int = 4) -> list[float]:
    """The n-quantile boundaries (n-1 edges) of a value list — the band cut
    points for income/population. Pure; ignores None. Returns [] when there is
    too little spread to form bands (all-equal or <n distinct values)."""
    vs = sorted(v for v in values if v is not None)
    if len(vs) < n or vs[0] == vs[-1]:
        return []
    edges: list[float] = []
    for i in range(1, n):
        pos = i * len(vs) / n
        lo = int(pos)
        if lo >= len(vs):
            lo = len(vs) - 1
        edges.append(float(vs[lo]))
    # de-duplicate collapsed edges (heavy ties) so bisect bands stay monotone
    dedup: list[float] = []
    for e in edges:
        if not dedup or e > dedup[-1]:
            dedup.append(e)
    return dedup


def band_of(value: Optional[float], edges: list[float]) -> Optional[int]:
    """The 0-based band index of `value` against sorted `edges` (bisect_right,
    so ties land in the upper band). None when the value or the edge set is
    missing — an unbanded dimension drops out of the cohort key."""
    if value is None or not edges:
        return None
    return bisect_right(edges, float(value))


def size_key(size_tier: Optional[str], population: Optional[float],
             pop_edges: list[float]) -> Optional[str]:
    """The size dimension of the cohort key. Prefer the scanner's own
    `size_tier` label; fall back to a population band when it's absent so a
    tier-less city still cohorts by size. None only when neither is available."""
    t = (size_tier or "").strip()
    if t:
        return f"t:{t}"
    b = band_of(population, pop_edges)
    return f"p:{b}" if b is not None else None


def cohort_keys(category_id: Optional[str], size: Optional[str],
                income_b: Optional[int]) -> list[tuple]:
    """The cohort keys from finest to coarsest for the fallback ladder:
      L0 (category, size, income)  — comparable size AND income
      L1 (category, size)          — comparable size only
      L2 (category)                — same trade, any market
    A level is emitted only when its dimensions are present."""
    cat = (category_id or "").strip()
    if not cat:
        return []
    keys: list[tuple] = []
    if size is not None and income_b is not None:
        keys.append(("cat_size_inc", cat, size, income_b))
    if size is not None:
        keys.append(("cat_size", cat, size))
    keys.append(("cat", cat))
    return keys


def field_signal(rev_win: Optional[float], cohort_median: Optional[float],
                 denom_floor: float = 5.0) -> Optional[float]:
    """Normalized field-strength signal in [-1, 1]: POSITIVE when this market's
    `rev_win` is below its cohort median (weaker field for its class → easier).
    The denom floor keeps tiny-median cohorts from amplifying noise. None when
    either input is missing."""
    if rev_win is None or cohort_median is None:
        return None
    denom = max(float(cohort_median), denom_floor)
    return _clamp((float(cohort_median) - float(rev_win)) / denom, -1.0, 1.0)


def compute_peer_signals(markets: list[dict[str, Any]], *, min_peers: int = 5,
                         denom_floor: float = 5.0
                         ) -> dict[tuple[int, str], dict[str, Any]]:
    """Board-wide peer-cohort field-strength for every market with a `rev_win`.

    Each market row: {city_id, category_id, category, rev_win, size_tier,
    population, income}. Returns {(city_id, category_id): {peer_field,
    cohort_level, cohort_n, cohort_median, rev_win, income_band}} — one entry
    per market that resolved to a cohort with ≥ min_peers at some level. Pure.
    """
    income_edges = quantile_edges([m.get("income") for m in markets], 4)
    pop_edges = quantile_edges([m.get("population") for m in markets], 4)

    # Decorate each market with its size key + income band once.
    decorated: list[dict[str, Any]] = []
    for m in markets:
        size = size_key(m.get("size_tier"), m.get("population"), pop_edges)
        inc_b = band_of(m.get("income"), income_edges)
        decorated.append({**m, "_size": size, "_inc": inc_b})

    # Accumulate rev_win samples per cohort key at every granularity level.
    samples: dict[tuple, list[float]] = {}
    for m in decorated:
        rw = m.get("rev_win")
        if rw is None:
            continue
        for key in cohort_keys(m.get("category_id"), m["_size"], m["_inc"]):
            samples.setdefault(key, []).append(float(rw))

    medians = {k: median(v) for k, v in samples.items()}
    counts = {k: len(v) for k, v in samples.items()}

    out: dict[tuple[int, str], dict[str, Any]] = {}
    for m in decorated:
        rw = m.get("rev_win")
        if rw is None:
            continue
        chosen = None
        for key in cohort_keys(m.get("category_id"), m["_size"], m["_inc"]):
            if counts.get(key, 0) >= min_peers:
                chosen = key
                break
        if chosen is None:
            continue
        med = medians.get(chosen)
        sig = field_signal(rw, med, denom_floor)
        if sig is None:
            continue
        out[(m["city_id"], m["category_id"])] = {
            "peer_field": round(sig, 4),
            "cohort_level": chosen[0],
            "cohort_n": counts.get(chosen, 0),
            "cohort_median": round(float(med), 1) if med is not None else None,
            "rev_win": round(float(rw), 1),
            "income_band": m["_inc"],
        }
    return out
