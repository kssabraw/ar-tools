"""Word-budget allocation + topic-adherence filter (M14 slice 3, PRD §5.4) — pure.

The cosine scoring for adherence is egress (embeddings) and lives in the pipeline; here
is the deterministic group math + the threshold drop given pre-computed scores.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import BriefHeading

CONCLUSION_BUDGET = 125          # §5.4.1 fixed 100–150
SECTION_FLOOR = 50               # §5.4.1 every section ≥50 words
ADHERENCE_THRESHOLD = 0.62       # §5.4.2
AUTHORITY_GAP_WEIGHT = 1.2       # §5.4.1 authority_gap_sme H3 weight


@dataclass
class Group:
    """A section group: a content parent H2 + its content child H3s (§5.4.1)."""

    parent: BriefHeading
    children: list[BriefHeading] = field(default_factory=list)


def group_headings(headings: list[BriefHeading]) -> list[Group]:
    """Partition the content headings into H2 groups (H3s attach to the preceding H2).
    Non-content rows (faq-*, conclusion) and any leading H1 are excluded."""
    groups: list[Group] = []
    for h in headings:
        if h.type != "content":
            continue
        if h.level == "H2":
            groups.append(Group(parent=h))
        elif h.level == "H3" and groups:
            groups[-1].children.append(h)
    return groups


def allocate_budget(
    headings: list[BriefHeading], *, word_budget: int = 2500,
    conclusion_budget: int = CONCLUSION_BUDGET, floor: int = SECTION_FLOOR,
) -> dict[int, int]:
    """`{heading.order: section_budget}` (§5.4.1). Equal per-group share of the body
    budget; within a group, authority-gap H3s pull a 1.2× weight from the parent. The
    conclusion row (type conclusion) gets the fixed conclusion budget. FAQ rows excluded."""
    groups = group_headings(headings)
    out: dict[int, int] = {}
    if groups:
        body_budget = max(0, word_budget - conclusion_budget)
        per_group = body_budget / len(groups)
        for g in groups:
            members = [g.parent, *g.children]
            weights = [
                AUTHORITY_GAP_WEIGHT if (m.level == "H3" and m.source == "authority_gap_sme") else 1.0
                for m in members
            ]
            wsum = sum(weights) or 1.0
            for m, w in zip(members, weights):
                out[m.order] = max(floor, round(per_group * w / wsum))
    for h in headings:
        if h.type == "conclusion":
            out[h.order] = conclusion_budget
    return out


def drop_low_adherence(
    headings: list[BriefHeading], scores: dict[int, float], *,
    threshold: float = ADHERENCE_THRESHOLD,
) -> tuple[list[int], list[dict]]:
    """§5.4.2 — drop content H2 groups whose parent H2 cosine-to-title `score` is below
    `threshold`; a dropped parent carries its child H3s. Authority-gap H3s are exempt
    from the check but still leave with a dropped parent. Returns `(kept_orders,
    dropped[{order, heading, score}])`. `kept_orders` covers H2s + their kept H3s; the
    caller keeps all non-content rows (FAQ / conclusion) regardless."""
    kept: list[int] = []
    dropped: list[dict] = []
    for g in group_headings(headings):
        score = scores.get(g.parent.order, 1.0)
        if score < threshold:
            dropped.append({"order": g.parent.order, "heading": g.parent.text, "score": round(score, 4)})
            continue
        kept.append(g.parent.order)
        kept.extend(c.order for c in g.children)
    return kept, dropped
