"""Director of Operations — cross-agent read model + reversible reconciler
(build spec: docs/modules/director-of-operations-phase1-spec-v1_0.md).

A read-only lens onto how work flows across SerMaStr (proposes), PACE
(executes), QA (judges), the autonomy executor (dark), and the deterministic
producers — all writing the native task board. NOT a fifth persona; its
conversational surface is SerMaStr (``_ctx_director`` in
``slack_assistant/context.py``). NEVER touches the three tested precedence
engines (``reopt_planner`` tiers, ``autonomy_policy.classify``, ``pm_assign``
holds) — it observes their outputs and escalates conflicts as proposals.

Submodules (grows inside PACE's watcher — not a new subsystem):

  read_model.py  — build_read_model(client_id | None, today) -> dict
  providers.py   — the isolated, best-effort provider functions
  seams.py       — pure seam predicates over the read model
  reconcile.py   — run_daily(today): the reversible board-task/notification pass
  digest.py      — run_weekly(today): the deterministic operations-flow digest
  veto.py        — preflight_conflict(rec, client_id): the dark autonomy veto

Ships dark: every piece is gated by its own ``director_*`` config flag,
default off/False.
"""

from __future__ import annotations

from services.director import digest, providers, read_model, reconcile, seams, veto
from services.director.digest import dedupe_key as digest_dedupe_key
from services.director.digest import run_weekly
from services.director.read_model import build_read_model
from services.director.reconcile import run_daily
from services.director.veto import preflight_conflict

__all__ = [
    "digest",
    "providers",
    "read_model",
    "reconcile",
    "seams",
    "veto",
    "build_read_model",
    "run_daily",
    "run_weekly",
    "digest_dedupe_key",
    "preflight_conflict",
]
