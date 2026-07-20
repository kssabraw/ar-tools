"""JSON-LD builder for blog posts: BlogPosting + FAQPage structured data.

Deterministic — no LLM. The blog Writer already carries everything schema needs
(title, FAQ question/answer pairs); publish-time context adds the rest
(publisher/brand, featured image, dates), so the graph is assembled here in
platform-api at publish time rather than in the pipeline Writer output.

Mirrors `modules/service_writer/jsonld.py` (the house pattern for the
service/location pages): a compact `{"@context", "@graph": [...]}` string. It is
threaded to the GitHub publish path as a frontmatter `schema:` value and injected
as a `<script type="application/ld+json">` block on the WordPress path.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

# Google's Article rich-result guidance caps a usable headline around 110 chars.
_HEADLINE_MAX = 110

_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_MD_CITATION_RE = re.compile(r"\[\d+\]")


def markdown_to_plain(text: str) -> str:
    """Flatten Markdown answer prose to a single plain-text string for schema.

    Structured data wants readable text, not Markdown: images are dropped, links
    become their anchor text, numeric citation markers (`[1]`) and inline marks
    (`*_` `` ` ``) are stripped, and whitespace/newlines collapse to single
    spaces."""
    if not text:
        return ""
    out = _MD_IMAGE_RE.sub("", text)
    out = _MD_LINK_RE.sub(r"\1", out)
    out = _MD_CITATION_RE.sub("", out)
    out = re.sub(r"[*_`]", "", out)
    out = re.sub(r"^\s{0,3}#{1,6}\s*", "", out, flags=re.MULTILINE)
    out = re.sub(r"\s+", " ", out)
    return out.strip()


def faqs_from_article(article: list[dict]) -> list[dict[str, str]]:
    """Extract `{question, answer}` pairs from the sources_cited enriched article.

    FAQ sections carry `type="faq-question"`, `heading`=question, `body`=answer
    (Markdown, possibly with inline citations). Answers are flattened to plain
    text; entries missing either half are skipped."""
    faqs: list[dict[str, str]] = []
    if not isinstance(article, list):
        return faqs
    for section in article:
        if not isinstance(section, dict):
            continue
        if section.get("type") != "faq-question":
            continue
        question = (section.get("heading") or "").strip()
        answer = markdown_to_plain(section.get("body") or "")
        if question and answer:
            faqs.append({"question": question, "answer": answer})
    return faqs


def _build_organization(
    *,
    name: str,
    url: str = "",
    logo_url: Optional[str] = None,
    same_as: Optional[list[str]] = None,
    telephone: Optional[str] = None,
) -> dict[str, Any]:
    """The client's brand as a schema.org Organization node.

    Carries an `@id` (derived from the site URL) so the post can reference the
    same entity from author + publisher instead of duplicating it, a `logo`
    (ImageObject — Google's Article guidance wants the publisher to have one),
    and `sameAs` links (e.g. the Google Business Profile) that tie the brand to
    known profiles. Returns {} when there's no name (nothing to describe)."""
    if not name or not name.strip():
        return {}
    org: dict[str, Any] = {"@type": "Organization"}
    url = (url or "").strip()
    if url:
        org["@id"] = f"{url.rstrip('/')}#organization"
    org["name"] = name.strip()
    if url:
        org["url"] = url
    if logo_url and logo_url.strip():
        org["logo"] = {"@type": "ImageObject", "url": logo_url.strip()}
    sa = [s.strip() for s in (same_as or []) if isinstance(s, str) and s.strip()]
    if sa:
        org["sameAs"] = sa
    if telephone and telephone.strip():
        org["telephone"] = telephone.strip()
    return org


def build_blog_jsonld(
    *,
    title: str,
    faqs: Optional[list[dict[str, str]]] = None,
    brand_name: str = "",
    site_url: str = "",
    logo_url: Optional[str] = None,
    same_as: Optional[list[str]] = None,
    telephone: Optional[str] = None,
    image_url: Optional[str] = None,
    date_published: Optional[str] = None,
    date_modified: Optional[str] = None,
    description: Optional[str] = None,
    url: Optional[str] = None,
) -> str:
    """Return a JSON-LD string with a BlogPosting node, the brand Organization,
    and (if FAQs) a FAQPage.

    All fields beyond `title` are optional and emitted only when present, so a
    thin post still yields a valid (if minimal) BlogPosting. Returns "" when
    there is no title (nothing meaningful to describe)."""
    headline = (title or "").strip()
    if not headline:
        return ""
    if len(headline) > _HEADLINE_MAX:
        headline = headline[:_HEADLINE_MAX].rstrip()

    graph: list[dict[str, Any]] = []

    org = _build_organization(
        name=brand_name,
        url=site_url,
        logo_url=logo_url,
        same_as=same_as,
        telephone=telephone,
    )
    # No author byline flows through the pipeline — the client/brand Organization
    # is the best available author + publisher. When it has a stable @id (a site
    # URL), emit it once as its own node and reference it by @id; otherwise inline.
    org_ref: Optional[dict[str, Any]] = None
    if org:
        if org.get("@id"):
            graph.append(org)
            org_ref = {"@id": org["@id"]}
        else:
            org_ref = org

    posting: dict[str, Any] = {"@type": "BlogPosting", "headline": headline}
    if description and description.strip():
        posting["description"] = description.strip()
    if image_url and image_url.strip():
        posting["image"] = image_url.strip()
    if date_published:
        posting["datePublished"] = date_published
    if date_modified:
        posting["dateModified"] = date_modified
    if org_ref:
        posting["author"] = org_ref
        posting["publisher"] = org_ref
    if url and url.strip():
        posting["mainEntityOfPage"] = {"@type": "WebPage", "@id": url.strip()}
    posting["inLanguage"] = "en"
    graph.append(posting)

    clean_faqs = [
        f for f in (faqs or [])
        if isinstance(f, dict) and f.get("question") and f.get("answer")
    ]
    if clean_faqs:
        graph.append({
            "@type": "FAQPage",
            "mainEntity": [
                {
                    "@type": "Question",
                    "name": f["question"],
                    "acceptedAnswer": {"@type": "Answer", "text": f["answer"]},
                }
                for f in clean_faqs
            ],
        })

    return json.dumps({"@context": "https://schema.org", "@graph": graph}, ensure_ascii=False)


def inline_jsonld_script(schema: str) -> str:
    """Wrap a JSON-LD string in a `<script type="application/ld+json">` block for
    embedding in HTML (the WordPress body). `<` is escaped to `\\u003c` so a stray
    `</script>` inside FAQ answer text can't terminate the block early; the result
    is still valid JSON."""
    if not schema or not schema.strip():
        return ""
    safe = schema.replace("<", "\\u003c")
    return f'<script type="application/ld+json">{safe}</script>'
