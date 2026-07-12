"""SOP library + module-card retrieval for SerMaStr (the strategist agent).

Two document corpora feed every strategist run (spec: docs/modules/
seo-strategist-agent-plan-v1_0.md §2/§2b):

  * ``docs/sops/`` — the agency's SOP corpus. The digest gets a token-budgeted
    selection of the docs *relevant to the client's active signals* (an open
    maps alert pulls the Maps drop SOP; an offpage alert pulls the Link
    Building SOP; the `_ORCHESTRATOR` router rides along always). The
    strategist can pull more via the ``read_sop`` drill-down tool.
  * ``docs/agents/module-cards/`` — per-instrument "how to read this" cards,
    injected whole into every run (they exist precisely to prevent instrument
    misreadings; they're small).

Deployment note: the platform-api Docker image is built from
``writer/platform-api`` only, so the repo-root ``docs/`` tree does not exist in
production. The docs are therefore **vendored** at
``writer/platform-api/agent_docs/`` (baked into the image); the loader prefers
the canonical repo-root copy when present (dev/sandbox) and falls back to the
vendored copy (prod). A unit test asserts the two stay byte-identical so the
vendored copy can't drift silently.

Everything here is pure file/string work (no DB, no network) — unit-tested.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

_SERVICE_ROOT = Path(__file__).resolve().parent.parent          # writer/platform-api
_REPO_ROOT = _SERVICE_ROOT.parent.parent                        # repo root (dev only)

# (canonical repo path, vendored in-image path)
_SOP_DIRS = (_REPO_ROOT / "docs" / "sops", _SERVICE_ROOT / "agent_docs" / "sops")
_CARD_DIRS = (
    _REPO_ROOT / "docs" / "agents" / "module-cards",
    _SERVICE_ROOT / "agent_docs" / "module-cards",
)

# Non-doc files in docs/sops (the capacity workbook is xlsx; README is meta).
_SOP_SKIP = {"README.md"}

_HEADING_RE = re.compile(r"^(#{1,3})\s+(.*)$", re.MULTILINE)

# Which SOP docs a given active-signal domain makes relevant, in priority order
# (earlier docs win budget). Domains are what build_strategy_digest reports as
# active: 'organic_drop', 'maps', 'offpage', 'ai_visibility', 'content', 'budget'.
# `_ORCHESTRATOR.md` is always first — it's the router + the global rules
# (halt-and-ask boundaries, shared definitions, roles matrix).
_ALWAYS = ["_ORCHESTRATOR.md"]
_RELEVANCE: dict[str, list[str]] = {
    "organic_drop": ["Rank_Drop_Mitigation_SOP_Organic.md"],
    "maps": ["Rank_Drop_Mitigation_SOP_Maps.md", "How_To_Rank_In_Google_Maps_SOP.md"],
    "offpage": ["Link_Building_SOP.md", "Link_Building_Recipe_Engine.md"],
    "budget": ["Link_Building_Recipe_Engine.md"],
    "ai_visibility": ["AIO_AEO_SOP.md"],
    "content": ["On_Page_Criteria_and_Coverage.md", "Site_Architecture_and_Internal_Linking_SOP.md"],
    # A client seeded from a LeadOff market pick (or a market-selection
    # question): the SOP carries the ×10 RD conversion + how to read the
    # entry-decision effort targets against live campaign data.
    "leadoff": ["LeadOff_Market_Intelligence_SOP.md"],
    # QA Agent grounding (qa-agent-plan §3b): the deliverable acceptance
    # checklists + the shared on-page verdict definition its narratives cite.
    "qa": ["QA_Checklists.md", "On_Page_Criteria_and_Coverage.md"],
}
# Per-doc character caps: the big SOPs would eat the whole budget otherwise.
_DOC_CAP_CHARS = {
    "Link_Building_SOP.md": 9_000,
    "Site_Architecture_and_Internal_Linking_SOP.md": 6_000,
    "How_To_Rank_In_Google_Maps_SOP.md": 8_000,
}
_DEFAULT_DOC_CAP = 14_000


def _first_existing(candidates: tuple[Path, ...]) -> Path | None:
    for c in candidates:
        if c.is_dir():
            return c
    return None


@lru_cache(maxsize=1)
def load_sop_docs() -> dict[str, str]:
    """{filename: text} for every SOP markdown doc. Cached (docs are static per
    deploy). Empty dict when neither directory exists (never raises)."""
    root = _first_existing(_SOP_DIRS)
    if root is None:
        logger.warning("sop_library.no_sop_dir")
        return {}
    out: dict[str, str] = {}
    for p in sorted(root.glob("*.md")):
        if p.name in _SOP_SKIP:
            continue
        try:
            out[p.name] = p.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("sop_library.read_failed", extra={"doc": p.name, "error": str(exc)})
    return out


@lru_cache(maxsize=1)
def load_module_cards() -> str:
    """All module cards concatenated into one prompt block ('' if absent).
    Injected whole into every strategist run — they are the instrument-reading
    rules and are deliberately compact."""
    root = _first_existing(_CARD_DIRS)
    if root is None:
        logger.warning("sop_library.no_card_dir")
        return ""
    parts: list[str] = []
    for p in sorted(root.glob("*.md")):
        try:
            parts.append(p.read_text(encoding="utf-8").strip())
        except OSError as exc:
            logger.warning("sop_library.card_read_failed", extra={"doc": p.name, "error": str(exc)})
    return "\n\n---\n\n".join(parts)


def split_sections(text: str) -> list[tuple[str, str]]:
    """[(heading, body)] for a markdown doc, split on #/##/### headings. The
    preamble before the first heading comes back under ''. Pure."""
    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        return [("", text.strip())] if text.strip() else []
    sections: list[tuple[str, str]] = []
    pre = text[: matches[0].start()].strip()
    if pre:
        sections.append(("", pre))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[m.end(): end].strip()
        sections.append((m.group(2).strip(), body))
    return sections


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit("\n", 1)[0]
    return cut.rstrip() + "\n…[truncated — use the read_sop tool for the full section]"


def relevant_docs(active_domains: set[str]) -> list[str]:
    """Ordered doc list for a set of active signal domains. Pure."""
    ordered: list[str] = list(_ALWAYS)
    for domain in ("organic_drop", "maps", "offpage", "budget", "ai_visibility", "content", "leadoff", "qa"):
        if domain in active_domains:
            for doc in _RELEVANCE[domain]:
                if doc not in ordered:
                    ordered.append(doc)
    return ordered


def qa_sops_text(budget_chars: int = 8_000) -> str:
    """The budgeted SOP block for a QA-review narrative: just the QA grounding
    docs (QA_Checklists + On-Page Criteria), WITHOUT the _ORCHESTRATOR — a QA
    narrative cites the acceptance standard, not the agency router."""
    docs = load_sop_docs()
    parts: list[str] = []
    remaining = budget_chars
    for name in _RELEVANCE["qa"]:
        text = docs.get(name)
        if not text or remaining <= 500:
            continue
        cap = min(_DOC_CAP_CHARS.get(name, _DEFAULT_DOC_CAP), remaining)
        block = f"### SOP DOC: {name}\n{_truncate(text.strip(), cap)}"
        parts.append(block)
        remaining -= len(block)
    return "\n\n".join(parts)


def select_sops_text(active_domains: set[str], budget_chars: int = 40_000) -> str:
    """The budgeted SOP block for a strategist run: the docs relevant to the
    client's active signals, in priority order, each capped, the whole block
    bounded by ``budget_chars``. Returns '' when no docs are loadable."""
    docs = load_sop_docs()
    if not docs:
        return ""
    parts: list[str] = []
    remaining = budget_chars
    for name in relevant_docs(active_domains):
        text = docs.get(name)
        if not text or remaining <= 500:
            continue
        cap = min(_DOC_CAP_CHARS.get(name, _DEFAULT_DOC_CAP), remaining)
        block = f"### SOP DOC: {name}\n{_truncate(text.strip(), cap)}"
        parts.append(block)
        remaining -= len(block)
    return "\n\n".join(parts)


def list_sop_sections() -> list[dict]:
    """Catalog of {doc, sections[]} — what the read_sop tool can fetch."""
    return [
        {"doc": name, "sections": [h for h, _ in split_sections(text) if h]}
        for name, text in load_sop_docs().items()
    ]


def read_sop(doc: str, section: str | None = None, max_chars: int = 8_000) -> str:
    """Fetch one SOP doc (or one section of it) for the read_sop drill-down
    tool. Doc matching is forgiving (case-insensitive, .md optional, substring);
    section matching is case-insensitive substring on the heading. Returns a
    clear not-found message rather than raising (the LLM reads the result)."""
    docs = load_sop_docs()
    if not docs:
        return "SOP library unavailable in this deployment."
    want = (doc or "").strip().lower().removesuffix(".md")
    match_name = None
    for name in docs:
        if name.lower().removesuffix(".md") == want:
            match_name = name
            break
    if match_name is None:
        for name in docs:
            if want and want in name.lower():
                match_name = name
                break
    if match_name is None:
        return f"No SOP doc matching '{doc}'. Available: {', '.join(sorted(docs))}"
    text = docs[match_name]
    if section:
        s_want = section.strip().lower()
        for heading, body in split_sections(text):
            if heading and s_want in heading.lower():
                return _truncate(f"## {heading}\n{body}", max_chars)
        headings = [h for h, _ in split_sections(text) if h]
        return (
            f"No section matching '{section}' in {match_name}. "
            f"Sections: {'; '.join(headings[:30])}"
        )
    return _truncate(text, max_chars)
