"""Resolve a cluster's internal-link targets from the M6 architecture graph (M15 slice 2).

Pure: given the stored `architecture_json` + per-cluster slugs + topic names + primary
keywords + the site base URL, produce the ordered `LinkTarget`s for one article. The job
(activation) fetches that data and feeds it here, then calls `link_injector.inject_links`.

Supporting article (a cluster) → its up-link (parent pillar) + lateral peer articles.
Pillar generation (silo-level) lands with the worker slice; here a non-supporting
`cluster_id` returns no targets.

URL shapes — default (handoff §9.5):
  pillar             {base}/{silo-slug}/
  supporting article {base}/{silo-slug}/{article-slug}

URL shapes — client-inferred (`url_style` from the client's blog-post reference URL,
e.g. https://client.com/blog/some-post/ → prefix "/blog/", trailing slash): the site's
real permalink structure has no per-silo directories, so pillars and articles are both
flat posts under the prefix:
  pillar             {base}{prefix}{silo-slug}[/]
  supporting article {base}{prefix}{article-slug}[/]
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from .link_injector import LinkTarget
from .slugs import slugify

# Owner rule (M6): at most this many outbound internal links per page.
MAX_OUTBOUND_LINKS = 5


@dataclass(frozen=True)
class UrlStyle:
    """A site's blog-post URL pattern, inferred from one example post URL."""

    prefix: str            # path before the post slug, "/" wrapped (e.g. "/blog/", "/")
    trailing_slash: bool   # whether post URLs end with "/"

    def post_url(self, base: str, slug: str) -> str:
        return f"{base.rstrip('/')}{self.prefix}{slug}" + ("/" if self.trailing_slash else "")


def infer_url_style(reference_url: str) -> UrlStyle | None:
    """Derive the blog-post URL pattern from one example post URL (the client card's
    blog-post reference page). The last path segment is taken to be the post's slug;
    everything before it is the fixed prefix.

      https://client.com/blog/how-to-fix-a-roof/  → prefix "/blog/", trailing slash
      https://client.com/how-to-fix-a-roof        → prefix "/",      no slash

    Returns None when no safe pattern can be derived: non-http(s)/malformed URLs, a
    bare domain root (no slug to strip), or a date-based permalink (a purely numeric
    prefix segment like /2026/07/slug/ — the date of an unpublished post can't be
    predicted, so the caller must fall back to the default scheme)."""
    try:
        parsed = urlparse((reference_url or "").strip())
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    path = parsed.path or "/"
    segments = [s for s in path.split("/") if s]
    if not segments:
        return None
    prefix_segments = segments[:-1]
    if any(s.isdigit() for s in prefix_segments):
        return None
    prefix = "/" + "/".join(prefix_segments) + "/" if prefix_segments else "/"
    return UrlStyle(prefix=prefix, trailing_slash=path.endswith("/"))


def build_extra_targets(urls: list[str] | None, *, limit: int = 3) -> list[LinkTarget]:
    """User-specified extra link targets (money pages — product/service/landing URLs the
    user wants every article to link to). The anchor phrase and title are derived from
    the URL's last path segment de-slugged ("/retatrutide-for-sale/" → "retatrutide for
    sale"); the injector links the first prose occurrence, falling back to the Related
    Articles list like any other target. Invalid/duplicate URLs are dropped; capped."""
    out: list[LinkTarget] = []
    seen: set[str] = set()
    for raw in urls or []:
        url = (raw or "").strip()
        if not url or url in seen:
            continue
        try:
            parsed = urlparse(url)
        except ValueError:
            continue
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            continue
        seen.add(url)
        segments = [s for s in (parsed.path or "").split("/") if s]
        phrase = segments[-1].replace("-", " ").replace("_", " ").strip() if segments else ""
        out.append(LinkTarget(
            url=url,
            anchors=[phrase] if phrase else [],
            title=phrase.title() if phrase else parsed.netloc,
        ))
        if len(out) >= limit:
            break
    return out


def merge_targets(
    targets: list[LinkTarget], extras: list[LinkTarget], *, cap: int = MAX_OUTBOUND_LINKS,
) -> list[LinkTarget]:
    """Fold user extras into an article's architecture targets under the ≤cap outbound
    rule. Priority: the up-link (first architecture target — mandatory per M6), then the
    user's extras (they asked for these explicitly), then remaining laterals until the
    cap. Deduped by URL."""
    ordered = (targets[:1] + extras + targets[1:]) if targets else list(extras)
    merged: list[LinkTarget] = []
    seen: set[str] = set()
    for t in ordered:
        if t.url in seen:
            continue
        seen.add(t.url)
        merged.append(t)
        if len(merged) >= cap:
            break
    return merged


def _silo_slug(topic_id: str, topics_by_id: dict[str, dict], fallback: str = "") -> str:
    name = (topics_by_id.get(topic_id) or {}).get("name") or fallback
    return slugify(name)


def build_targets(
    cluster_id: str, *, architecture: dict, clusters_by_id: dict[str, dict],
    topics_by_id: dict[str, dict], keywords_by_id: dict[str, str], base_url: str,
    url_style: UrlStyle | None = None,
) -> tuple[list[LinkTarget], bool]:
    """`(targets, is_pillar)` for `cluster_id`. Empty when the cluster isn't a supporting
    article in the architecture (gap placeholder / not yet planned). With a `url_style`
    (inferred from the client's blog-post reference URL), URLs follow the site's real
    flat permalink pattern instead of the default per-silo directory scheme."""
    base = (base_url or "").rstrip("/")
    supporting = {a["article_id"]: a for a in architecture.get("supporting_articles", [])}
    pillars_by_topic = {p["topic_id"]: p for p in architecture.get("pillars", [])}

    node = supporting.get(cluster_id)
    if not node:
        return [], False

    targets: list[LinkTarget] = []
    seen_urls: set[str] = set()

    # Up-link to the parent pillar (mandatory). Default scheme: the pillar page lives at
    # the silo root; client-inferred scheme: the pillar is a flat post whose slug is the
    # silo slug.
    pillar = pillars_by_topic.get(node.get("parent_pillar_topic_id"))
    if pillar:
        silo = _silo_slug(pillar["topic_id"], topics_by_id, pillar.get("silo_name", ""))
        url = url_style.post_url(base, silo) if url_style else f"{base}/{silo}/"
        anchors = [a for a in (pillar.get("target_keyword"), pillar.get("silo_name")) if a]
        targets.append(LinkTarget(
            url=url, anchors=anchors,
            title=pillar.get("title") or pillar.get("silo_name") or "Overview"))
        seen_urls.add(url)

    # Lateral links to peer supporting articles.
    for peer_id in node.get("lateral_article_links", []):
        peer = clusters_by_id.get(peer_id)
        if not peer or not peer.get("slug"):
            continue
        silo = _silo_slug(peer["topic_id"], topics_by_id)
        url = (url_style.post_url(base, peer["slug"]) if url_style
               else f"{base}/{silo}/{peer['slug']}")
        if url in seen_urls:
            continue
        kw = keywords_by_id.get(peer.get("primary_keyword_id"))
        peer_name = (supporting.get(peer_id) or {}).get("name") or peer.get("name")
        anchors = [a for a in (kw, peer_name) if a]
        targets.append(LinkTarget(url=url, anchors=anchors, title=peer_name or kw or "Related Article"))
        seen_urls.add(url)

    return targets, False
