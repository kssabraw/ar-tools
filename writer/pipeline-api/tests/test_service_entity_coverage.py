"""Service page entity-coverage enforcement (Option B) — pure-logic units.

Covers the aggressive-competitor benchmark (service_brief.entity_benchmark) and
the coverage/rewrite math (service_writer.entity_coverage).
"""

import asyncio

from modules.service_brief.entity_benchmark import (
    aggressive_entity_target,
    counts_from_source_urls,
)
from modules.service_writer.entity_coverage import (
    _entity_present,
    compute_coverage,
    enforce_entity_coverage,
)


# --- aggressive_entity_target ---------------------------------------------

def test_target_is_max_of_competitors():
    # Three competitors cover 5, 8, 6 distinct entities → most aggressive = 8.
    assert aggressive_entity_target([5, 8, 6]) == 8


def test_target_excludes_spam_outlier():
    # median of [3,3,3,3,30] is 3; 30 > 3×3 → dropped → max of the rest = 3.
    assert aggressive_entity_target([3, 3, 3, 3, 30]) == 3


def test_target_keeps_high_but_legit_competitor():
    # median of [4,5,6,10] is 5.5; 10 <= 3×5.5 → kept → 10.
    assert aggressive_entity_target([4, 5, 6, 10]) == 10


def test_target_plain_max_below_three_competitors():
    # No stable median with <3 values → plain max, outlier or not.
    assert aggressive_entity_target([2, 40]) == 40


def test_target_zero_when_empty():
    assert aggressive_entity_target([]) == 0
    assert aggressive_entity_target([0, 0]) == 0


def test_counts_from_source_urls():
    # entity A on pages 1,2 ; B on page 1 ; C on pages 1,2,3
    per_url = counts_from_source_urls([["p1", "p2"], ["p1"], ["p1", "p2", "p3"]])
    assert per_url == {"p1": 3, "p2": 2, "p3": 1}
    assert aggressive_entity_target(per_url.values()) == 3


# --- _entity_present -------------------------------------------------------

def test_entity_present_word_boundary_single_token():
    assert _entity_present("ai", "ai powers this tool")
    assert not _entity_present("ai", "our training program")  # not inside 'training'


def test_entity_present_multiword_substring():
    assert _entity_present("water heater", "we do water heater repair")
    assert not _entity_present("water heater", "we repair water tanks")


# --- compute_coverage ------------------------------------------------------

def test_compute_coverage_triggers_below_floor():
    pool = ["burst pipe", "blocked drain", "water heater", "sump pump", "gas line"]
    text = "We fix burst pipe issues."  # only 1 of 5 present
    stats = compute_coverage(pool, text, target=5, floor=0.75)
    assert stats.pool_size == 5
    assert stats.target == 5
    assert stats.covered == 1
    assert stats.needed == 4  # round(0.75 × 5)
    assert stats.rewrite_triggered is True
    assert set(stats.missing) == {"blocked drain", "water heater", "sump pump", "gas line"}


def test_compute_coverage_target_clamped_to_pool():
    pool = ["burst pipe", "blocked drain"]  # only 2 available
    stats = compute_coverage(pool, "burst pipe blocked drain", target=10, floor=0.75)
    assert stats.target == 2          # clamped to pool size, not 10
    assert stats.covered == 2
    assert stats.rewrite_triggered is False


def test_compute_coverage_met_does_not_trigger():
    pool = ["a term", "b term", "c term", "d term"]
    text = "a term b term c term"  # 3 of 4, needed = round(0.75×4)=3
    stats = compute_coverage(pool, text, target=4, floor=0.75)
    assert stats.covered == 3 and stats.needed == 3
    assert stats.rewrite_triggered is False


# --- enforce_entity_coverage ----------------------------------------------

class _Sec:
    def __init__(self, heading, text, type="content"):
        self.heading = heading
        self.blocks = [text]
        self.type = type


def _block_text(blocks):
    return " ".join(str(b) for b in (blocks or []))


def test_enforce_rewrites_weakest_and_recovers():
    pool = ["burst pipe", "blocked drain", "water heater", "sump pump"]
    # Two content sections: one already covers 2 entities, one covers none.
    strong = _Sec("Repairs", "burst pipe and blocked drain work")
    weak = _Sec("About", "we are a friendly local team")
    faq = _Sec("FAQ", "no entities here", type="faq")
    sections = [strong, weak, faq]

    async def regen(section, missing):
        # The rewrite works the missing entities into the section.
        return [f"{section.heading}: " + ", ".join(missing)]

    stats = asyncio.run(enforce_entity_coverage(
        sections, pool=pool, target=4, floor=0.75,
        max_sections=3, regen_section=regen, block_text_fn=_block_text,
    ))
    assert stats.rewrite_triggered is True
    assert stats.sections_rewritten == 1          # only the weak content section needed it
    assert stats.covered == 4                      # all four now present
    # The faq section (type != content) is never rewritten.
    assert faq.blocks == ["no entities here"]


def test_enforce_noop_when_covered():
    pool = ["burst pipe", "blocked drain"]
    sec = _Sec("Repairs", "burst pipe and blocked drain")

    async def regen(section, missing):  # pragma: no cover - must not be called
        raise AssertionError("regen should not run when coverage is met")

    stats = asyncio.run(enforce_entity_coverage(
        [sec], pool=pool, target=2, floor=0.75,
        max_sections=3, regen_section=regen, block_text_fn=_block_text,
    ))
    assert stats.rewrite_triggered is False
    assert stats.sections_rewritten == 0
