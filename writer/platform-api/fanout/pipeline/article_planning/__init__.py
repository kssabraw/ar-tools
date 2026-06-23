"""M5 article planning (PRD §7.10): editorial orchestrator + cross-topic dedup.

Turns the per-topic statistical groupings from §7.9 into a plan of articles
(`clusters`), with a SERP fetch per candidate primary keyword feeding the
orchestrator's merge/split/promote-demote/route/drop decisions, followed by a
deterministic cross-topic dedup pass.
"""
