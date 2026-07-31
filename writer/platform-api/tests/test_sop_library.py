"""Unit tests for services.sop_library — SOP/module-card retrieval for SerMaStr.

Pure file/string logic; no DB or network. Also guards the vendored
``agent_docs/`` copies (baked into the Docker image, which can't see the
repo-root ``docs/`` tree) against drifting from the canonical docs.
"""

from __future__ import annotations

from pathlib import Path

from services import sop_library

SERVICE_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = SERVICE_ROOT.parent.parent


# ---------------------------------------------------------------------------
# Vendored-copy sync guard
# ---------------------------------------------------------------------------
def _assert_dirs_identical(canonical: Path, vendored: Path) -> None:
    canon_files = {p.name for p in canonical.glob("*.md")}
    vend_files = {p.name for p in vendored.glob("*.md")}
    assert canon_files == vend_files, (
        f"agent_docs drifted from {canonical}: only-in-canonical="
        f"{canon_files - vend_files}, only-in-vendored={vend_files - canon_files}. "
        "Re-copy the docs into writer/platform-api/agent_docs/."
    )
    for name in canon_files:
        assert (canonical / name).read_text() == (vendored / name).read_text(), (
            f"agent_docs/{vendored.name}/{name} differs from the canonical copy — "
            "re-copy it (the Docker image ships the vendored copy)."
        )


def test_vendored_sops_match_canonical():
    canonical = REPO_ROOT / "docs" / "sops"
    if not canonical.is_dir():  # image-only environment: nothing to compare
        return
    _assert_dirs_identical(canonical, SERVICE_ROOT / "agent_docs" / "sops")


def test_vendored_module_cards_match_canonical():
    canonical = REPO_ROOT / "docs" / "agents" / "module-cards"
    if not canonical.is_dir():
        return
    _assert_dirs_identical(canonical, SERVICE_ROOT / "agent_docs" / "module-cards")


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
def test_load_sop_docs_finds_the_corpus():
    docs = sop_library.load_sop_docs()
    assert "_ORCHESTRATOR.md" in docs
    assert "Rank_Drop_Mitigation_SOP_Organic.md" in docs
    assert "README.md" not in docs  # meta file skipped


def test_load_module_cards_concatenates_all():
    cards = sop_library.load_module_cards()
    assert "Organic Rank Tracker" in cards
    assert "Geo-Grid" in cards
    assert "AI Visibility" in cards


# ---------------------------------------------------------------------------
# Section splitting
# ---------------------------------------------------------------------------
def test_split_sections_headings_and_preamble():
    text = "intro line\n\n# Title\nbody a\n\n## Sub One\nbody b\n### Deep\nbody c\n"
    sections = sop_library.split_sections(text)
    headings = [h for h, _ in sections]
    assert headings == ["", "Title", "Sub One", "Deep"]
    assert dict(sections)["Sub One"] == "body b"


def test_split_sections_no_headings():
    assert sop_library.split_sections("just text") == [("", "just text")]
    assert sop_library.split_sections("   \n") == []


# ---------------------------------------------------------------------------
# Relevance + budgeting
# ---------------------------------------------------------------------------
def test_relevant_docs_always_includes_orchestrator_first():
    docs = sop_library.relevant_docs(set())
    assert docs[0] == "_ORCHESTRATOR.md"


def test_relevant_docs_maps_domains_to_docs():
    docs = sop_library.relevant_docs({"maps", "offpage"})
    assert "Rank_Drop_Mitigation_SOP_Maps.md" in docs
    assert "Link_Building_SOP.md" in docs
    # organic-only doc is not pulled in
    assert "Rank_Drop_Mitigation_SOP_Organic.md" not in docs


def test_relevant_docs_dedupes_overlapping_domains():
    docs = sop_library.relevant_docs({"offpage", "budget"})
    assert docs.count("Link_Building_Recipe_Engine.md") == 1


def test_relevant_docs_leadoff_domain():
    docs = sop_library.relevant_docs({"leadoff"})
    assert "LeadOff_Market_Intelligence_SOP.md" in docs
    assert docs[0] == "_ORCHESTRATOR.md"


def test_relevant_docs_qa_domain():
    docs = sop_library.relevant_docs({"qa"})
    assert "QA_Checklists.md" in docs
    assert "On_Page_Criteria_and_Coverage.md" in docs
    assert docs[0] == "_ORCHESTRATOR.md"


def test_qa_sops_text_serves_qa_docs_without_orchestrator():
    text = sop_library.qa_sops_text(budget_chars=16_000)
    assert text.startswith("### SOP DOC: QA_Checklists.md")
    # The BLOCK HEADER, not a filename mention — QA_Checklists' cross-references
    # section names the On-Page doc, which made a substring assertion pass even
    # when the doc itself was budget-starved out (adversarial review 2026-07-12).
    assert "### SOP DOC: On_Page_Criteria_and_Coverage.md" in text
    assert "### SOP DOC: _ORCHESTRATOR.md" not in text
    # Both docs must arrive UNTRUNCATED at the default budget (no '…' elision
    # marker), so the bands + blocking rules the narrative cites are present.
    from config import settings

    full = sop_library.qa_sops_text(settings.qa_sop_budget_chars)
    assert "### SOP DOC: On_Page_Criteria_and_Coverage.md" in full
    # Budget bounded (one-doc-cap overshoot max, same contract as select_sops_text).
    small = sop_library.qa_sops_text(budget_chars=2_000)
    assert len(small) < len(text)
    assert "### SOP DOC: On_Page_Criteria_and_Coverage.md" not in small


def test_select_sops_text_respects_budget():
    full = sop_library.select_sops_text({"organic_drop", "maps", "offpage", "content"}, budget_chars=200_000)
    small = sop_library.select_sops_text({"organic_drop", "maps", "offpage", "content"}, budget_chars=12_000)
    assert len(small) < len(full)
    # Budget overshoot is bounded by one doc cap, not unbounded.
    assert len(small) <= 12_000 + sop_library._DEFAULT_DOC_CAP
    assert small.startswith("### SOP DOC: _ORCHESTRATOR.md")


def test_select_sops_text_empty_domains_still_has_orchestrator():
    text = sop_library.select_sops_text(set())
    assert "_ORCHESTRATOR.md" in text


# ---------------------------------------------------------------------------
# read_sop (drill-down tool)
# ---------------------------------------------------------------------------
def test_read_sop_whole_doc_fuzzy_name():
    out = sop_library.read_sop("rank_drop_mitigation_sop_organic")
    assert "Rank Drop" in out or "rank" in out.lower()


def test_read_sop_section_match():
    out = sop_library.read_sop("_ORCHESTRATOR", "Global Agent Rules")
    assert "halt-and-ask" in out.lower()


def test_read_sop_unknown_doc_lists_available():
    out = sop_library.read_sop("no_such_doc")
    assert out.startswith("No SOP doc matching")
    assert "_ORCHESTRATOR.md" in out


def test_read_sop_unknown_section_lists_headings():
    out = sop_library.read_sop("_ORCHESTRATOR", "nonexistent section title")
    assert out.startswith("No section matching")


def test_read_sop_truncates():
    out = sop_library.read_sop("Link_Building_SOP", max_chars=500)
    assert len(out) < 700
    assert "read_sop tool" in out  # truncation marker


def test_router_doc_cannot_starve_the_topic_sops():
    """_ORCHESTRATOR is 14k raw. At the chat's SOP budget it was taking ~87% of
    the block, truncating away the doc that actually answered the question —
    the mechanism behind the 2026-07-30 generic-advice turn. It's now bounded to
    a third of the budget."""
    text = sop_library.select_sops_text({"maps_growth", "maps"}, budget_chars=24_000)
    blocks = dict(_doc_blocks(text))
    assert "_ORCHESTRATOR.md" in blocks
    assert len(blocks["_ORCHESTRATOR.md"]) <= 24_000 // 3 + 200  # + heading slack
    # The growth playbook survives the budget rather than being squeezed out.
    assert "How_To_Rank_In_Google_Maps_SOP.md" in blocks
    assert len(blocks["How_To_Rank_In_Google_Maps_SOP.md"]) > 5_000


def test_maps_growth_orders_the_how_to_rank_doc_first():
    """A growth question ('how can we rank in <city>') wants the How-To-Rank SOP
    ahead of the drop-mitigation one; a drop question keeps the old order."""
    growth = sop_library.relevant_docs({"maps_growth", "maps"})
    assert growth.index("How_To_Rank_In_Google_Maps_SOP.md") < growth.index(
        "Rank_Drop_Mitigation_SOP_Maps.md"
    )
    drop = sop_library.relevant_docs({"maps"})
    assert drop.index("Rank_Drop_Mitigation_SOP_Maps.md") < drop.index(
        "How_To_Rank_In_Google_Maps_SOP.md"
    )


def _doc_blocks(text: str):
    """[(doc_name, body)] parsed out of a rendered SOP block."""
    import re

    marks = list(re.finditer(r"### SOP DOC: (\S+)\n", text))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        yield m.group(1), text[m.end():end]


# ---------------------------------------------------------------------------
# Budget order is question-shaped (2026-07-31).
#
# The Jupiter growth turn spent 6.7k of a 24k budget on Rank_Drop_Mitigation
# (pulled in merely because the client HAS a geo-grid) and left AIO_AEO_SOP with
# 1,973 of its 12,741 chars — the theory, none of Part 2's tactics. The AI
# section of that answer was "add keywords to tracking", because that was
# genuinely all the model had.
# ---------------------------------------------------------------------------


def test_growth_turn_funds_channel_playbooks_before_diagnostics():
    docs = sop_library.relevant_docs({"maps_growth", "ai_visibility", "content"})
    assert docs.index("How_To_Rank_In_Google_Maps_SOP.md") < docs.index("AIO_AEO_SOP.md")
    assert docs.index("AIO_AEO_SOP.md") < docs.index("On_Page_Criteria_and_Coverage.md")


def test_diagnostic_turn_still_leads_with_the_mitigation_playbooks():
    docs = sop_library.relevant_docs(
        {"organic_drop", "maps", "maps_growth", "ai_visibility", "content"}
    )
    assert docs.index("Rank_Drop_Mitigation_SOP_Organic.md") < docs.index("AIO_AEO_SOP.md")
    assert docs.index("Rank_Drop_Mitigation_SOP_Maps.md") < docs.index("AIO_AEO_SOP.md")


def test_growth_turn_gives_the_aeo_sop_enough_room_for_its_tactics():
    # Part 2 (the Platform-Influence Matrix — G Stacks for AIO, Medium/LinkedIn/
    # Reddit for LLMs) starts past the 2k mark. A slice that stops short of it
    # leaves the model with theory and no actions.
    from config import settings

    text = sop_library.select_sops_text(
        {"maps_growth", "ai_visibility", "content"},
        budget_chars=settings.slack_assistant_sop_budget_chars,
    )
    start = text.index("### SOP DOC: AIO_AEO_SOP.md")
    nxt = text.find("### SOP DOC:", start + 10)
    slice_len = (nxt if nxt > 0 else len(text)) - start
    assert slice_len > 6_000, f"AEO SOP only got {slice_len} chars"
    assert "Platform-Influence Matrix" in text


# ---------------------------------------------------------------------------
# Whole docs, or an explicit deferral — never a silent fragment.
#
# select_sops_text used to size each doc at min(cap, remaining), so the last in
# the queue got the scraps. On the Jupiter turn AIO_AEO_SOP — 12,741 chars,
# under its 14k cap, so it should have arrived whole — got 1,973: Part 1's
# theory and none of Part 2's tactics. A fragment is worse than an omission,
# because nothing in it says the half that answered the question was cut.
# ---------------------------------------------------------------------------

_GROWTH = {"maps_growth", "ai_visibility", "content"}


def test_a_doc_under_its_cap_arrives_whole():
    text = sop_library.select_sops_text(_GROWTH, budget_chars=60_000)
    raw = sop_library.load_sop_docs()["AIO_AEO_SOP.md"]
    start = text.index("### SOP DOC: AIO_AEO_SOP.md")
    nxt = text.find("### SOP DOC", start + 10)
    got = (nxt if nxt > 0 else len(text)) - start
    assert got >= len(raw) - 100, f"AEO SOP truncated to {got} of {len(raw)}"
    # Part 2 is where the tactics live; the theory alone is what caused the bug.
    assert "Platform-Influence Matrix" in text


def test_no_doc_is_emitted_as_a_starved_fragment():
    # A budget too small for everything must drop whole docs, not shave the tail.
    text = sop_library.select_sops_text(_GROWTH, budget_chars=30_000)
    docs = sop_library.load_sop_docs()
    import re

    for m in re.finditer(r"### SOP DOC: (\S+)", text):
        name = m.group(1)
        start = m.end()
        nxt = text.find("### SOP DOC", start)
        got = (nxt if nxt > 0 else len(text)) - start
        cap = sop_library._DOC_CAP_CHARS.get(name, sop_library._DEFAULT_DOC_CAP)
        if name in sop_library._ALWAYS:
            # The router is deliberately bounded to a third of the block so the
            # topic SOPs behind it still fit; that's a cap, not starvation.
            cap = min(cap, max(30_000 // 3, 1_000))
        wanted = min(cap, len(docs[name]))
        assert got >= wanted * sop_library._MIN_USEFUL_FRACTION, (
            f"{name} got {got}, under {sop_library._MIN_USEFUL_FRACTION:.0%} of its {wanted}"
        )


def test_docs_that_dont_fit_are_named_not_silently_dropped():
    text = sop_library.select_sops_text(_GROWTH, budget_chars=30_000)
    assert "SOP DOCS NOT INLINED" in text
    assert "read_sop" in text


def test_a_generous_budget_leaves_nothing_deferred_on_a_growth_turn():
    text = sop_library.select_sops_text(_GROWTH, budget_chars=60_000)
    assert "SOP DOCS NOT INLINED" not in text
