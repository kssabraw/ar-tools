"""Run scope vs deep-mine gate — the pure selection logic (PRD §7.2 + run scope).

A fanout run carries two independent per-silo selections:

* **run scope** — the silos the pipeline works on at all: expansion, the
  relevance gate, clustering, article planning.
* **deep-mine gate** — which of those silos *additionally* get competitor
  mining (the paid SERP -> ranked-keywords step). The seed is always mined.

They were conflated before: only the gate existed, so a user who ticked 3 of 5
silos on the "choose silos to deep-mine" screen still had all 5 expanded and
planned. This module resolves a request's two lists against the session's silos
so the API layer only has to map an error to an HTTP status.
"""

from dataclasses import dataclass


class SelectionError(ValueError):
    """A silo selection that cannot be honoured. `detail` is user-facing."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True)
class Selection:
    run_topic_ids: list[str]
    gated_topic_ids: list[str]


def resolve_selection(
    *,
    all_topic_ids: list[str],
    topic_ids: list[str],
    run_topic_ids: list[str] | None,
) -> Selection:
    """Validate and normalize a deep-mine request.

    `run_topic_ids` of None means "every silo" — what every caller predating the
    run-scope control sends, so their behaviour is unchanged. Both lists are
    deduped with order preserved.
    """
    valid = set(all_topic_ids)

    gated = list(dict.fromkeys(topic_ids))
    unknown = [tid for tid in gated if tid not in valid]
    if unknown:
        raise SelectionError(
            f"Topics do not belong to this session: {', '.join(unknown)}"
        )

    if run_topic_ids is None:
        return Selection(run_topic_ids=list(all_topic_ids), gated_topic_ids=gated)

    scope = list(dict.fromkeys(run_topic_ids))
    unknown_scope = [tid for tid in scope if tid not in valid]
    if unknown_scope:
        raise SelectionError(
            f"Topics do not belong to this session: {', '.join(unknown_scope)}"
        )
    if not scope:
        raise SelectionError("Select at least one silo to run.")

    # Mining a silo the run skips would spend SERP budget on keywords nothing
    # downstream reads. Reject rather than silently narrowing the selection —
    # a quiet drop looks identical to the bug this control exists to fix.
    orphaned = [tid for tid in gated if tid not in set(scope)]
    if orphaned:
        raise SelectionError(
            "A silo cannot be deep-mined while it is excluded from the run. "
            "Include it in the run or clear its deep-mine choice."
        )

    return Selection(run_topic_ids=scope, gated_topic_ids=gated)
