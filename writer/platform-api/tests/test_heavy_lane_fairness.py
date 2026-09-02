"""Bulk-lane per-client fairness ordering (`order_candidates_by_fairness`).

The rule: one client's bulk batch can hold at most `max_per_client` bulk slots
CONCURRENTLY while another client also has bulk work pending — so a 40-page batch
can't starve another client's batch. Contention-only: a client alone in the
window still gets claimed (the ordering never DROPS a candidate, only reorders),
so no slot is idled. Only engages with >1 bulk worker; the ordering itself is
pure and worker-count-agnostic.
"""

from services.job_worker import order_candidates_by_fairness


def _cand(cid, jid):
    return {"id": jid, "entity_id": cid}


def test_no_cap_leaves_order_unchanged():
    cands = [_cand("A", 1), _cand("B", 2), _cand("A", 3)]
    assert order_candidates_by_fairness(cands, {"A": 5}, None) == cands
    assert order_candidates_by_fairness(cands, {"A": 5}, 0) == cands


def test_capped_client_is_tried_after_under_cap_clients():
    cands = [_cand("A", 1), _cand("A", 2), _cand("B", 3)]
    out = order_candidates_by_fairness(cands, {"A": 2, "B": 0}, 2)
    assert [j["id"] for j in out] == [3, 1, 2]  # B (under cap) first, then A's in order


def test_stable_within_groups_preserves_queue_order():
    cands = [_cand("A", 1), _cand("B", 2), _cand("A", 3), _cand("C", 4)]
    out = order_candidates_by_fairness(cands, {"A": 2}, 2)  # A capped; B,C under
    assert [j["id"] for j in out] == [2, 4, 1, 3]


def test_capped_client_alone_is_still_claimable_not_idled():
    cands = [_cand("A", 1), _cand("A", 2), _cand("A", 3)]
    out = order_candidates_by_fairness(cands, {"A": 3}, 2)
    assert [j["id"] for j in out] == [1, 2, 3]


def test_client_exactly_under_cap_is_not_treated_as_capped():
    cands = [_cand("A", 1), _cand("B", 2)]
    out = order_candidates_by_fairness(cands, {"A": 1, "B": 0}, 2)
    assert [j["id"] for j in out] == [1, 2]  # neither at cap → unchanged
