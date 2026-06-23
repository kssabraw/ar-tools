"""CSV export generation (PRD §12).

Pure, side-effect-free CSV builders over already-fetched Postgres rows. Keeping
generation pure means it is fully unit-testable with no Supabase/egress access —
which matters because the *Storage* upload + signed-URL layer (app/storage/
exports.py) cannot be exercised in the sandbox at all. All correctness coverage
lives on these functions.

Three formats (PRD §12):
  - flat          — one row per keyword, the §9.1 Table View columns.
  - topic_grouped — one CSV per topic, delivered as a single .zip (one file =
                    one storage_path), one entry per topic.
  - architecture  — one row per page (pillar or supporting article).

CSV formula injection (a.k.a. CSV/Excel injection): a cell whose text begins with
=, +, -, @ (or a leading tab / carriage return) is interpreted as a formula by
spreadsheet apps. Every exported text cell is hardened by prefixing a single
quote so the value renders literally. Numeric columns are formatted by us and
never begin with a dangerous character, so the guard is a harmless no-op on them.
"""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import datetime, timezone

# Table View columns (PRD §9.1). Volume / KD / CPC stay blank — metrics
# enrichment (§7.8) is unbuilt (optional in v1).
FLAT_HEADERS = [
    "keyword",
    "topic",
    "cluster",
    "source",
    "volume",
    "kd",
    "cpc",
    "relevance",
    "status",
]

ARCHITECTURE_HEADERS = [
    "page_type",
    "title",
    "target_keyword",
    "parent_pillar",
    "outline_h2s",
    "internal_links_out",
]

# Internal-linking matrix (PRD §7.11 / §12, follow-on): one row per edge in the
# site graph so the user can pivot/sort by from-page or to-page in a spreadsheet
# without splitting the architecture CSV's joined `internal_links_out` cell.
# link_type is one of: pillar_to_article (pillar -> its supporting articles),
# article_to_pillar (the mandatory up-link), pillar_to_pillar (lateral, M6 §15.2
# #4), article_to_article (lateral peer, §7.11 "2-3 lateral links").
LINKING_HEADERS = [
    "from_page",
    "from_type",
    "to_page",
    "to_type",
    "link_type",
]

_DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _safe(value: object) -> str:
    """Stringify a value and neutralize CSV formula injection. A leading single
    quote is the canonical mitigation (renders the cell as literal text)."""
    if value is None:
        return ""
    text = str(value)
    if text and text[0] in _DANGEROUS_PREFIXES:
        return "'" + text
    return text


def _rows_to_csv(headers: list[str], rows: list[list[object]]) -> str:
    """Render a header + sanitized rows to a CSV string (CRLF line endings, the
    RFC-4180 default csv.writer uses)."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    for row in rows:
        writer.writerow([_safe(cell) for cell in row])
    return buf.getvalue()


def _fmt_relevance(score: object) -> str:
    if score is None:
        return ""
    try:
        return f"{float(score):.4f}"
    except (TypeError, ValueError):
        return ""


def _fmt_metric(value: object) -> str:
    # Volume / KD / CPC are null today (metrics enrichment unbuilt); format any
    # future value plainly so it never trips the formula guard.
    if value is None:
        return ""
    return str(value)


def _flat_row(
    kw: dict,
    topic_name: dict[str, str],
    cluster_name: dict[str | None, str],
) -> list[object]:
    return [
        kw.get("keyword") or "",
        topic_name.get(kw.get("topic_id"), ""),
        cluster_name.get(kw.get("cluster_id"), "Unassigned" if not kw.get("cluster_id") else ""),
        ", ".join(kw.get("sources") or []),
        _fmt_metric(kw.get("volume")),
        _fmt_metric(kw.get("kd")),
        _fmt_metric(kw.get("cpc_usd")),
        _fmt_relevance(kw.get("relevance_score")),
        kw.get("status") or "",
    ]


def build_flat_csv(
    keywords: list[dict],
    topic_name: dict[str, str],
    cluster_name: dict[str | None, str],
) -> str:
    """Flat keyword list (PRD §12 #1): one row per keyword, Table View columns."""
    rows = [_flat_row(k, topic_name, cluster_name) for k in keywords]
    return _rows_to_csv(FLAT_HEADERS, rows)


def build_topic_grouped_csvs(
    keywords: list[dict],
    topic_name: dict[str, str],
    cluster_name: dict[str | None, str],
) -> list[tuple[str, str]]:
    """Topic-grouped (PRD §12 #2): one CSV per topic. Returns (filename, csv)
    pairs, ordered by topic name, ready to zip. Keywords with an unknown topic id
    (shouldn't happen — FK-backed) are grouped under an "_unassigned-topic" file
    so nothing is silently dropped."""
    by_topic: dict[str, list[dict]] = {}
    for k in keywords:
        by_topic.setdefault(k.get("topic_id") or "", []).append(k)

    named: list[tuple[str, str]] = []
    # Order by display name for a stable, human-friendly zip.
    ordered_tids = sorted(by_topic, key=lambda tid: topic_name.get(tid, "~").lower())
    used_names: set[str] = set()
    for tid in ordered_tids:
        display = topic_name.get(tid) or "_unassigned-topic"
        filename = _unique_filename(_slug(display), used_names)
        csv_text = build_flat_csv(by_topic[tid], topic_name, cluster_name)
        named.append((filename, csv_text))
    return named


def build_architecture_csv(
    architecture_json: dict,
    article_name_by_id: dict[str, str],
    pillar_title_by_topic: dict[str, str],
    target_kw_by_article: dict[str, str],
    h2s_by_article: dict[str, list[str]],
) -> str:
    """Site-architecture (PRD §12 #3): one row per page (pillar or supporting
    article) with page_type, title, target_keyword, parent_pillar, outline_h2s,
    internal_links_out.

    Link/title columns are resolved to human-readable names (article names,
    pillar titles) rather than raw ids — the CSV is for sharing, not re-import.
    """
    pillars = architecture_json.get("pillars") or []
    supporting = architecture_json.get("supporting_articles") or []
    rows: list[list[object]] = []

    for p in pillars:
        # Down-links to this pillar's supporting articles + lateral pillar peers.
        down = [article_name_by_id.get(aid, aid) for aid in (p.get("supporting_article_ids") or [])]
        lateral = [pillar_title_by_topic.get(tid, tid) for tid in (p.get("lateral_pillar_links") or [])]
        rows.append([
            "pillar",
            p.get("title") or p.get("silo_name") or "",
            p.get("target_keyword") or "",
            "",  # pillars are top-level — no parent
            " | ".join(p.get("h2_outline") or []),
            " | ".join(down + lateral),
        ])

    for a in supporting:
        aid = a.get("article_id")
        parent = pillar_title_by_topic.get(a.get("parent_pillar_topic_id"), "")
        lateral = [article_name_by_id.get(lid, lid) for lid in (a.get("lateral_article_links") or [])]
        links_out = list(lateral)
        if parent:
            links_out.append(parent)  # the mandatory up-link to the pillar
        rows.append([
            "supporting",
            a.get("name") or "",
            target_kw_by_article.get(aid, ""),
            parent,
            " | ".join(h2s_by_article.get(aid) or []),
            " | ".join(links_out),
        ])

    return _rows_to_csv(ARCHITECTURE_HEADERS, rows)


def build_linking_csv(
    architecture_json: dict,
    article_name_by_id: dict[str, str],
    pillar_title_by_topic: dict[str, str],
) -> str:
    """Flat from-page -> to-page edge list for the site's internal linking
    graph (companion to `build_architecture_csv` which keeps the links joined
    in a single cell per page). One row per directed edge; the user can sort
    by from_page or to_page in a spreadsheet to audit hubs / leaks. Edges are
    written in a deterministic order (pillars in source order, then their
    supporting articles, then laterals) so a re-export is diff-stable.
    """
    pillars = architecture_json.get("pillars") or []
    supporting = architecture_json.get("supporting_articles") or []
    rows: list[list[object]] = []

    for p in pillars:
        from_title = p.get("title") or p.get("silo_name") or ""
        # Pillar -> supporting articles (down-links). Guaranteed by M6's
        # deterministic linking matrix.
        for aid in (p.get("supporting_article_ids") or []):
            to_title = article_name_by_id.get(aid, aid)
            rows.append([from_title, "pillar", to_title, "article", "pillar_to_article"])
        # Pillar -> pillar (lateral, only above the topic-embedding cosine
        # threshold per §15.2 #4).
        for tid in (p.get("lateral_pillar_links") or []):
            to_title = pillar_title_by_topic.get(tid, tid)
            rows.append([from_title, "pillar", to_title, "pillar", "pillar_to_pillar"])

    for a in supporting:
        aid = a.get("article_id")
        from_title = a.get("name") or aid or ""
        parent_topic = a.get("parent_pillar_topic_id")
        parent_title = pillar_title_by_topic.get(parent_topic, "")
        # Article -> pillar (mandatory up-link).
        if parent_title:
            rows.append([from_title, "article", parent_title, "pillar", "article_to_pillar"])
        # Article -> article (lateral peer, within-silo + cross-silo).
        for lid in (a.get("lateral_article_links") or []):
            to_title = article_name_by_id.get(lid, lid)
            rows.append([from_title, "article", to_title, "article", "article_to_article"])

    return _rows_to_csv(LINKING_HEADERS, rows)


def zip_named_csvs(named_csvs: list[tuple[str, str]]) -> bytes:
    """Pack (filename, csv) pairs into a single in-memory .zip (PRD §12: one
    storage_path per export). Deterministic — no timestamps in the archive."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for filename, text in named_csvs:
            zf.writestr(filename, text)
    return buf.getvalue()


def _slug(name: str) -> str:
    keep = [c.lower() if c.isalnum() else "-" for c in name.strip()]
    slug = "".join(keep).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return (slug or "topic")[:60]


def _unique_filename(base: str, used: set[str]) -> str:
    """Disambiguate two topics that slug to the same name (e.g. punctuation-only
    differences) so no zip entry is overwritten."""
    candidate = f"{base}.csv"
    i = 2
    while candidate in used:
        candidate = f"{base}-{i}.csv"
        i += 1
    used.add(candidate)
    return candidate


def snapshot_timestamp() -> str:
    """UTC timestamp for the storage path / object name (PRD §12 path shape).
    Filesystem-safe (no colons)."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
