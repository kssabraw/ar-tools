"""Deterministic blog-article structure analysis for the blog/AEO scorer.

Pure Python (+ BeautifulSoup) — no LLM, no network. Encodes the content-quality
PRD's structural acceptance checks that a scorer can measure exactly rather than
ask a model to judge:
  • R4 — a "Key Takeaways" block (the top-of-article AEO snippet target).
  • R6 — paragraphs capped at 4 sentences.
  • R7 — external citations on factual claims.
plus scannability (lists), heading structure, and length.

Used two ways in main.py: `detect_blog_structure` renders the facts injected into
the scoring prompt (so the LLM doesn't re-count), and `compute_blog_structural_aeo`
is the deterministic `structural_aeo` engine score (like serp_signal_coverage).
Kept as a standalone module so it is unit-testable without importing main.py.
"""

from __future__ import annotations

import re
from typing import List

# Common abbreviations whose internal periods must not count as sentence
# terminators in the paragraph-length check (content-quality PRD R6).
_BLOG_ABBREV = [
    "e.g.", "i.e.", "etc.", "vs.", "mr.", "mrs.", "ms.", "dr.", "prof.",
    "inc.", "ltd.", "co.", "u.s.", "u.k.", "st.", "jr.", "sr.", "no.",
    "approx.", "fig.", "est.", "dept.",
]


def count_sentences(text: str) -> int:
    """Approximate sentence count for a paragraph, collapsing common
    abbreviations first so 'e.g.'/'U.S.' don't inflate the count."""
    t = re.sub(r"\s+", " ", (text or "").strip())
    if not t:
        return 0
    for ab in _BLOG_ABBREV:
        t = re.sub(re.escape(ab), ab.replace(".", ""), t, flags=re.IGNORECASE)
    n = len(re.findall(r"[.!?]+(?:\s|$)", t))
    return max(1, n)


def structure_metrics(page_html: str) -> dict:
    """Raw deterministic measurements of a blog article's HTML, shared by the
    prompt-facts renderer and the structural_aeo engine scorer."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(page_html or "", "html.parser")
    h2 = len(soup.find_all("h2"))
    h3 = len(soup.find_all("h3"))
    lists = len(soup.find_all("ul")) + len(soup.find_all("ol"))
    tables = len(soup.find_all("table"))

    heading_texts = [h.get_text(" ", strip=True).lower() for h in soup.find_all(["h2", "h3"])]
    has_key_takeaways = any("key takeaway" in t for t in heading_texts)

    paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
    paragraphs = [p for p in paragraphs if p]
    long_paragraphs = sum(1 for p in paragraphs if count_sentences(p) > 4)

    external_links = 0
    for a in soup.find_all("a", href=True):
        href = a["href"].strip().lower()
        if href.startswith("http://") or href.startswith("https://"):
            external_links += 1
    # Citation markers survive when scoring a suite-reconstructed article that
    # hasn't had markers resolved to links yet.
    cite_markers = len(re.findall(r"\{\{\s*cit", page_html or "", flags=re.IGNORECASE))

    words = len(re.findall(r"\b\w+\b", soup.get_text(" ", strip=True)))
    return {
        "h2": h2, "h3": h3, "lists": lists, "tables": tables,
        "has_key_takeaways": has_key_takeaways,
        "paragraphs": len(paragraphs), "long_paragraphs": long_paragraphs,
        "citations": max(external_links, cite_markers),
        "words": words,
    }


def detect_blog_structure(page_html: str) -> str:
    """Deterministic structure facts for the blog scorer prompt (headings, lists,
    paragraph-length violations, citations, word count). The LLM is told not to
    re-count these."""
    m = structure_metrics(page_html)
    lines = ["HTML STRUCTURE FACTS (deterministic — do NOT override or re-count):"]
    lines.append(
        f"  • H2 sections: {m['h2']}, H3 sub-sections: {m['h3']}"
        + ("" if m["h2"] >= 3 else " ✗ thin — expected ≥3 H2 sections")
    )
    lines.append(
        f"  • 'Key Takeaways' block: {'present ✓' if m['has_key_takeaways'] else 'MISSING ✗ (AEO snippet block expected near top)'}"
    )
    lines.append(f"  • <ul>/<ol> lists: {m['lists']}" + ("" if m["lists"] >= 1 else " ✗ no scannable list found"))
    lines.append(
        f"  • Paragraphs over the 4-sentence cap: {m['long_paragraphs']} of {m['paragraphs']}"
        + ("" if m["long_paragraphs"] == 0 else " ✗ (readability/extractability)")
    )
    lines.append(
        f"  • External citations/links: {m['citations']}"
        + ("" if m["citations"] >= 1 else " ✗ none — factual claims should be sourced")
    )
    lines.append(f"  • Approx. word count: {m['words']}")
    return "\n".join(lines)


def compute_blog_structural_aeo(page_html: str) -> dict:
    """The deterministic structural_aeo engine: encodes R4 (Key Takeaways block),
    R6 (≤4-sentence paragraphs), R7 (citations), plus scannability and heading
    structure. Returns {score, issues, recommendations} like the serp coverage
    engine, so it drops straight into the scores dict."""
    m = structure_metrics(page_html)
    score = 100
    issues: List[str] = []
    recs: List[str] = []

    if not m["has_key_takeaways"]:
        score -= 20
        issues.append("No 'Key Takeaways' block — the top-of-article AEO snippet target is missing (R4).")
        recs.append("Add a 'Key Takeaways' H2 with 3–5 short standalone bullets after the H1; make the first bullet a direct answer to the query.")
    if m["h2"] < 3:
        score -= 15
        issues.append(f"Only {m['h2']} H2 section(s) — the article is structurally thin.")
        recs.append("Break the piece into at least 3 focused H2 sections covering distinct sub-topics.")
    if m["lists"] < 1:
        score -= 10
        issues.append("No bulleted/numbered list — hurts scannability and LLM extraction.")
        recs.append("Add at least one scannable list high on the page.")
    if m["long_paragraphs"] > 0:
        score -= min(25, m["long_paragraphs"] * 5)
        issues.append(f"{m['long_paragraphs']} paragraph(s) exceed the 4-sentence cap (R6).")
        recs.append("Split long paragraphs on a logical break; aim for 3 sentences or fewer.")
    if m["citations"] < 1:
        score -= 15
        issues.append("No external citations/links — factual claims are unsourced (R7, weak E-E-A-T).")
        recs.append("Cite authoritative external sources on time-bound, statistical, or named-source claims.")
    if m["words"] < 300:
        score -= 15
        issues.append(f"Very short article (~{m['words']} words) — likely insufficient depth.")
        recs.append("Expand coverage to fully answer the search intent.")

    return {"score": max(0, score), "issues": issues, "recommendations": recs}
