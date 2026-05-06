"""Tests for the authority-gap H3 displacement logic in assembly.py
(PRD §5 Step 8.6 - Authority Gap H3 Interaction)."""

from __future__ import annotations

import math

import pytest

from modules.brief.assembly import (
    MAX_H3_PER_H2,
    attach_authority_h3s_with_displacement,
)
from modules.brief.graph import Candidate


def _normalize(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v))
    return v if n == 0 else [x / n for x in v]


def _h2(text: str, embedding: list[float]) -> Candidate:
    c = Candidate(text=text, source="serp")  # type: ignore[arg-type]
    c.embedding = _normalize(embedding)
    return c


def _h3(
    text: str,
    embedding: list[float],
    *,
    priority: float = 0.5,
    is_authority: bool = False,
) -> Candidate:
    c = Candidate(
        text=text,
        source="authority_gap_sme" if is_authority else "serp",  # type: ignore[arg-type]
    )
    c.embedding = _normalize(embedding)
    c.heading_priority = priority
    c.exempt = is_authority
    return c


# ----------------------------------------------------------------------
# Capacity available - straightforward attach
# ----------------------------------------------------------------------

def test_authority_h3_attaches_to_most_similar_h2_when_capacity_available():
    h2_a = _h2("How TikTok Shop Works", [1.0, 0.0, 0.0])
    h2_b = _h2("Why TikTok Shop Matters", [0.0, 1.0, 0.0])
    auth = _h3("Risk and compliance gaps", [0.95, 0.31, 0.0],
               priority=0.6, is_authority=True)
    res = attach_authority_h3s_with_displacement(
        h2s=[h2_a, h2_b],
        authority_h3s=[auth],
        existing_attachments={0: [], 1: []},
    )
    assert res.attachments[0] == [auth]
    assert res.attachments[1] == []
    assert res.displaced == []


def test_authority_h3_inserted_at_index_0_so_it_reads_first():
    h2 = _h2("How TikTok Shop Works", [1.0, 0.0, 0.0])
    existing = _h3("Setup process", [0.7, 0.7, 0.0], priority=0.5)
    auth = _h3("Risk gaps", [0.95, 0.31, 0.0], priority=0.6, is_authority=True)
    res = attach_authority_h3s_with_displacement(
        h2s=[h2],
        authority_h3s=[auth],
        existing_attachments={0: [existing]},
    )
    assert res.attachments[0] == [auth, existing]


# ----------------------------------------------------------------------
# Cap full → priority displacement
# ----------------------------------------------------------------------

def test_authority_h3_displaces_weakest_existing_h3_when_cap_full():
    h2 = _h2("How TikTok Shop Works", [1.0, 0.0, 0.0])
    weak = _h3("Weak existing H3", [0.7, 0.7, 0.0], priority=0.2)
    strong = _h3("Strong existing H3", [0.71, 0.7, 0.0], priority=0.7)
    auth = _h3("Auth H3", [0.95, 0.31, 0.0],
               priority=0.5, is_authority=True)
    # Cap is 2; both slots filled
    res = attach_authority_h3s_with_displacement(
        h2s=[h2],
        authority_h3s=[auth],
        existing_attachments={0: [weak, strong]},
    )
    # Weak gets displaced, strong stays, auth inserted at index 0
    assert auth in res.attachments[0]
    assert strong in res.attachments[0]
    assert weak not in res.attachments[0]
    assert res.displaced == [weak]
    assert weak.discard_reason == "displaced_by_authority_gap_h3"


def test_authority_h3_with_lower_priority_routes_to_next_h2():
    """When the most-similar H2 has a stronger lowest-H3 than the auth H3,
    the auth H3 routes to the next-most-relevant H2."""
    h2_a = _h2("Most similar H2", [1.0, 0.0, 0.0])
    h2_b = _h2("Adjacent H2", [0.7, 0.7, 0.0])
    # H2-A has two strong H3s - auth would lose displacement here.
    a1 = _h3("A1 strong", [0.8, 0.6, 0.0], priority=0.9)
    a2 = _h3("A2 strong", [0.85, 0.5, 0.0], priority=0.85)
    # H2-B has capacity available
    auth = _h3("Auth", [0.99, 0.14, 0.0],
               priority=0.4, is_authority=True)
    res = attach_authority_h3s_with_displacement(
        h2s=[h2_a, h2_b],
        authority_h3s=[auth],
        existing_attachments={0: [a1, a2], 1: []},
    )
    # Auth should route to H2-B (which has capacity), not displace from A
    assert auth in res.attachments[1]
    assert a1 in res.attachments[0]
    assert a2 in res.attachments[0]
    assert res.displaced == []


# ----------------------------------------------------------------------
# Edge case: auth H3 has lowest priority everywhere → cap exceeded by 1
# ----------------------------------------------------------------------

def test_authority_h3_kept_even_when_lowest_priority_everywhere():
    h2 = _h2("H2", [1.0, 0.0, 0.0])
    a1 = _h3("a1", [0.7, 0.7, 0.0], priority=0.9)
    a2 = _h3("a2", [0.71, 0.7, 0.0], priority=0.8)
    # Auth has priority lower than all existing → can't displace anyone
    auth = _h3("Auth", [0.85, 0.5, 0.0],
               priority=0.1, is_authority=True)
    res = attach_authority_h3s_with_displacement(
        h2s=[h2],
        authority_h3s=[auth],
        existing_attachments={0: [a1, a2]},
    )
    # Auth is kept anyway - cap exceeded by 1
    assert auth in res.attachments[0]
    assert len(res.attachments[0]) == 3  # over the 2-cap
    assert res.displaced == []  # nothing displaced


def test_cap_overflow_logs(caplog):
    h2 = _h2("H2", [1.0, 0.0, 0.0])
    a1 = _h3("a1", [0.7, 0.7, 0.0], priority=0.9)
    a2 = _h3("a2", [0.71, 0.7, 0.0], priority=0.8)
    auth = _h3("Auth", [0.85, 0.5, 0.0], priority=0.1, is_authority=True)
    with caplog.at_level("INFO", logger="modules.brief.assembly"):
        attach_authority_h3s_with_displacement(
            h2s=[h2],
            authority_h3s=[auth],
            existing_attachments={0: [a1, a2]},
        )
    assert any(r.message == "brief.authority.cap_overflow" for r in caplog.records)


# ----------------------------------------------------------------------
# Multiple authority H3s - processed in priority-desc order
# ----------------------------------------------------------------------

def test_multiple_authority_h3s_processed_by_priority_desc():
    """When two auth H3s compete for the same H2, the higher-priority one
    gets first pick of capacity / displacement target."""
    h2 = _h2("H2", [1.0, 0.0, 0.0])
    weak_existing = _h3("weak", [0.7, 0.7, 0.0], priority=0.3)
    auth_low = _h3("auth low", [0.95, 0.31, 0.0],
                   priority=0.5, is_authority=True)
    auth_high = _h3("auth high", [0.95, 0.31, 0.0],
                    priority=0.9, is_authority=True)
    # Cap is 2; one slot taken
    res = attach_authority_h3s_with_displacement(
        h2s=[h2],
        authority_h3s=[auth_low, auth_high],  # input order doesn't matter
        existing_attachments={0: [weak_existing]},
    )
    # auth_high attaches first (priority 0.9), filling the second slot
    # auth_low arrives next; both slots full; auth_low displaces weak_existing
    # (priority 0.5 > 0.3).
    assert auth_high in res.attachments[0]
    assert auth_low in res.attachments[0]
    assert weak_existing in res.displaced
    assert weak_existing.discard_reason == "displaced_by_authority_gap_h3"


# ----------------------------------------------------------------------
# No H2s
# ----------------------------------------------------------------------

def test_no_h2s_skips_authority_h3s():
    auth = _h3("Auth", [0.7, 0.7, 0.0], is_authority=True)
    res = attach_authority_h3s_with_displacement(
        h2s=[],
        authority_h3s=[auth],
        existing_attachments={},
    )
    assert res.attachments == {}
    assert res.displaced == []


def test_empty_authority_h3s_returns_unchanged_attachments():
    h2 = _h2("H2", [1.0, 0.0, 0.0])
    existing = _h3("h3", [0.7, 0.7, 0.0])
    res = attach_authority_h3s_with_displacement(
        h2s=[h2],
        authority_h3s=[],
        existing_attachments={0: [existing]},
    )
    assert res.attachments[0] == [existing]
    assert res.displaced == []


# ----------------------------------------------------------------------
# Cap-respecting basic behavior
# ----------------------------------------------------------------------

def test_cap_respected_when_authority_can_fit_in_other_h2():
    """If H2-A is full and H2-B has capacity, auth H3 routes to H2-B
    even if H2-A is more similar."""
    h2_a = _h2("Most similar H2", [1.0, 0.0, 0.0])
    h2_b = _h2("Less similar H2", [0.7, 0.7, 0.0])
    a1 = _h3("a1", [0.95, 0.31, 0.0], priority=0.9)
    a2 = _h3("a2", [0.94, 0.31, 0.0], priority=0.88)
    auth = _h3("Auth", [0.99, 0.14, 0.0],
               priority=0.95, is_authority=True)
    # H2-A is full and auth's priority IS higher than weakest (0.95 > 0.88)
    # → auth WOULD displace under H2-A. But H2-B has capacity, so per
    # the algorithm step 1 (capacity-first), auth goes to H2-B instead.
    res = attach_authority_h3s_with_displacement(
        h2s=[h2_a, h2_b],
        authority_h3s=[auth],
        existing_attachments={0: [a1, a2], 1: []},
    )
    assert auth in res.attachments[1]
    assert res.displaced == []
    assert len(res.attachments[0]) == MAX_H3_PER_H2  # untouched


def test_constants_match_prd():
    assert MAX_H3_PER_H2 == 2
