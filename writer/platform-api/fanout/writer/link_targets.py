"""Resolve a cluster's internal-link targets from the M6 architecture graph (M15 slice 2).

Pure: given the stored `architecture_json` + per-cluster slugs + topic names + primary
keywords + the site base URL, produce the ordered `LinkTarget`s for one article. The job
(activation) fetches that data and feeds it here, then calls `link_injector.inject_links`.

Supporting article (a cluster) → its up-link (parent pillar) + lateral peer articles.
Pillar generation (silo-level) lands with the worker slice; here a non-supporting
`cluster_id` returns no targets.

URL shapes (handoff §9.5):
  pillar             {base}/{silo-slug}/
  supporting article {base}/{silo-slug}/{article-slug}
"""

from __future__ import annotations

from .link_injector import LinkTarget
from .slugs import slugify


def _silo_slug(topic_id: str, topics_by_id: dict[str, dict], fallback: str = "") -> str:
    name = (topics_by_id.get(topic_id) or {}).get("name") or fallback
    return slugify(name)


def build_targets(
    cluster_id: str, *, architecture: dict, clusters_by_id: dict[str, dict],
    topics_by_id: dict[str, dict], keywords_by_id: dict[str, str], base_url: str,
) -> tuple[list[LinkTarget], bool]:
    """`(targets, is_pillar)` for `cluster_id`. Empty when the cluster isn't a supporting
    article in the architecture (gap placeholder / not yet planned)."""
    base = (base_url or "").rstrip("/")
    supporting = {a["article_id"]: a for a in architecture.get("supporting_articles", [])}
    pillars_by_topic = {p["topic_id"]: p for p in architecture.get("pillars", [])}

    node = supporting.get(cluster_id)
    if not node:
        return [], False

    targets: list[LinkTarget] = []
    seen_urls: set[str] = set()

    # Up-link to the parent pillar (mandatory; the pillar's own page lives at the silo root).
    pillar = pillars_by_topic.get(node.get("parent_pillar_topic_id"))
    if pillar:
        silo = _silo_slug(pillar["topic_id"], topics_by_id, pillar.get("silo_name", ""))
        url = f"{base}/{silo}/"
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
        url = f"{base}/{silo}/{peer['slug']}"
        if url in seen_urls:
            continue
        kw = keywords_by_id.get(peer.get("primary_keyword_id"))
        peer_name = (supporting.get(peer_id) or {}).get("name") or peer.get("name")
        anchors = [a for a in (kw, peer_name) if a]
        targets.append(LinkTarget(url=url, anchors=anchors, title=peer_name or kw or "Related Article"))
        seen_urls.add(url)

    return targets, False
