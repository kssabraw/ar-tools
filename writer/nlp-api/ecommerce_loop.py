"""Pure control-flow decisions for the ecommerce auto-retry (keep-best) loop.

`/reoptimize-ecommerce-page` runs up to `MAX_ECOMMERCE_AUTO_PASSES` rewrite→score
passes, breaking when the page clears its `score_threshold`. That break cannot
tell a run that is climbing slowly apart from one that has flat-lined — both burn
every pass, at roughly 3m40s and $0.22 each. Roughly a third of observed runs
plateau below threshold and pay for the last pass anyway.

`should_stop_early` is the additional exit: it answers "did this pass gain enough
to justify another one?" and nothing else. Kept pure and separate from `main.py`
so the decision is unit-testable without an LLM.

The guard is OFF by default (`ECOMMERCE_MIN_PASS_GAIN=0`) — per-pass scores were
not observable anywhere until the logging that ships alongside this module, so
there is no calibration data yet. Enable on the `nlp` service once a batch of
real runs has been measured.
"""

from __future__ import annotations

from typing import Optional


def should_stop_early(
    prev_best: Optional[float],
    current: Optional[float],
    min_gain: float,
) -> bool:
    """True when the loop should stop because the pass gained too little.

    `prev_best` is the best score BEFORE this pass was folded in (None on pass 1
    — and whenever no pass has scored yet), `current` is this pass's score, and
    `min_gain` is the minimum improvement that justifies another pass.

    - `min_gain <= 0` disables the guard entirely (the shipped default).
    - Pass 1 never stops here: with no prior there is no gain to measure.
    - An unscored pass never stops here either — the caller's existing
      `pass_score is None` break owns that case.
    - A REGRESSION satisfies the same condition and stops, which is the intent:
      a pass that went backwards is a stronger plateau signal than a small gain,
      and keep-best already protects the output.
    """
    if min_gain <= 0:
        return False
    if prev_best is None or current is None:
        return False
    return (current - prev_best) < min_gain
