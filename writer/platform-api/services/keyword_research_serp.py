"""Keyword Research — SERP enrichment (People Also Ask + competitive intelligence).

For the first N seeds of a run the module makes one live Google SERP call each
(reusing services/serp_snapshot's fetch + parsers) and derives two things from
that single billed call per seed:

  * **People Also Ask** — the PAA questions Google shows for the seed. Folded into
    the keyword universe (so they cluster + export + tag as questions) AND kept
    as a raw list for a dedicated "questions people ask" display.
  * **Competitive intelligence** — the SERP landscape: the top organic domains
    across the analyzed seeds (with best position + which seeds they rank for)
    and who is cited in the AI Overview. This is *who you're up against* for these
    topics — SERP-scoped, distinct from the domain-level Domain Intelligence
    module (which does keyword/backlink gap for a named competitor).

The aggregation math here is PURE (no I/O) and independently unit-tested; the
per-seed SERP fetch is I/O and lives in services/keyword_research.py, reusing
serp_snapshot so there's one SERP parser in the suite.
"""

from __future__ import annotations

from typing import Optional


def _norm_domain(domain: Optional[str]) -> str:
    """Lower-cased bare domain (drop a leading www.). Pure."""
    d = (domain or "").strip().lower()
    return d[4:] if d.startswith("www.") else d


def dedupe_paa(paa_lists: list[list[str]], cap: int = 100) -> list[str]:
    """Flatten per-seed PAA question lists into an ordered, case-insensitively
    deduped list. Preserves first-seen order, caps the count. Pure."""
    out: list[str] = []
    seen: set[str] = set()
    for lst in paa_lists or []:
        for q in lst or []:
            s = " ".join(str(q or "").split()).strip()
            if not s:
                continue
            key = s.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(s)
            if len(out) >= cap:
                return out
    return out


def aggregate_competitors(
    per_seed_organic: list[dict],
    client_domain: Optional[str] = None,
    aio_domains: Optional[set[str]] = None,
    top_n: int = 10,
) -> list[dict]:
    """Aggregate the top organic results across analyzed seeds into a competitor
    landscape.

    ``per_seed_organic`` is a list of {seed, organic: [{position, url, domain,
    title, description}]} — one per analyzed seed. Returns competitor rows sorted
    by SERP presence (appearances desc, then best position asc):
    {domain, appearances, best_position, seeds, sample_title, sample_url,
    aio_cited, is_client}. The client's own domain is flagged (is_client=True) but
    kept in the list so "am I even here" is visible. Pure."""
    aio_domains = {_norm_domain(d) for d in (aio_domains or set())}
    client = _norm_domain(client_domain)
    agg: dict[str, dict] = {}
    for entry in per_seed_organic or []:
        seed = entry.get("seed")
        for o in entry.get("organic") or []:
            domain = _norm_domain(o.get("domain"))
            if not domain:
                continue
            pos = o.get("position")
            row = agg.get(domain)
            if row is None:
                row = {
                    "domain": domain,
                    "appearances": 0,
                    "best_position": pos,
                    "seeds": [],
                    "sample_title": o.get("title"),
                    "sample_url": o.get("url"),
                    "aio_cited": domain in aio_domains,
                    "is_client": bool(client) and domain == client,
                }
                agg[domain] = row
            row["appearances"] += 1
            if seed and seed not in row["seeds"]:
                row["seeds"].append(seed)
            if pos is not None and (row["best_position"] is None or pos < row["best_position"]):
                row["best_position"] = pos
                row["sample_title"] = o.get("title")
                row["sample_url"] = o.get("url")

    rows = list(agg.values())
    rows.sort(key=lambda r: (-r["appearances"], r["best_position"] if r["best_position"] is not None else 999))
    return rows[:top_n]


def aggregate_aio(per_seed_aio: list[dict], top_n: int = 12) -> dict:
    """Aggregate AI-Overview presence + cited sources across analyzed seeds.

    ``per_seed_aio`` is a list of {seed, present, sources: [{url, domain, title}]}.
    Returns {seeds_with_aio, seeds_analyzed, sources: [{domain, url, title,
    count}]} — sources ranked by how many seeds cited that domain. Pure."""
    total = len(per_seed_aio or [])
    with_aio = 0
    by_domain: dict[str, dict] = {}
    for entry in per_seed_aio or []:
        if entry.get("present"):
            with_aio += 1
        for s in entry.get("sources") or []:
            domain = _norm_domain(s.get("domain"))
            if not domain:
                continue
            row = by_domain.get(domain)
            if row is None:
                row = {"domain": domain, "url": s.get("url"), "title": s.get("title"), "count": 0}
                by_domain[domain] = row
            row["count"] += 1
    sources = sorted(by_domain.values(), key=lambda r: -r["count"])[:top_n]
    return {"seeds_with_aio": with_aio, "seeds_analyzed": total, "sources": sources}


def build_serp_intel(
    seeds_analyzed: list[str],
    per_seed_organic: list[dict],
    per_seed_aio: list[dict],
    paa_lists: list[list[str]],
    client_domain: Optional[str] = None,
    *,
    top_competitors: int = 10,
) -> dict:
    """Assemble the persisted serp_intel blob from per-seed SERP extracts. Pure."""
    aio = aggregate_aio(per_seed_aio)
    aio_domains = {s["domain"] for s in aio.get("sources") or []}
    competitors = aggregate_competitors(
        per_seed_organic, client_domain, aio_domains, top_n=top_competitors
    )
    return {
        "enabled": True,
        "seeds_analyzed": list(seeds_analyzed),
        "competitors": competitors,
        "aio": aio,
        "paa": dedupe_paa(paa_lists),
    }
