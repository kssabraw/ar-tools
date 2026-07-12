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
    text = sop_library.qa_sops_text()
    assert text.startswith("### SOP DOC: QA_Checklists.md")
    assert "On_Page_Criteria_and_Coverage.md" in text
    assert "_ORCHESTRATOR.md" not in text
    # Budget bounded (one-doc-cap overshoot max, same contract as select_sops_text).
    small = sop_library.qa_sops_text(budget_chars=2_000)
    assert len(small) < len(text)


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
