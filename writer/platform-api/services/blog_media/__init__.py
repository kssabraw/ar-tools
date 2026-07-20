"""Blog media pipeline (hero + inline images/charts for GitHub-published posts).

A deterministic, app-owned pipeline layered over the article: the app assigns
stable IDs, computes the media budget, validates the model's media plan, renders
assets, resolves placement against real element IDs, and inserts `<figure>`
blocks idempotently — the language model only *proposes* the plan (see
`docs`/the media-planning prompt). Built in phases; Phase 1 is the deterministic
core (IDs, budget, placement, insertion) + the planner call + hero/inline images.

Submodules:
  - article_html:  render the article to HTML with stable IDs, build the anchor
    index, resolve placements, insert figures into the committed body (pure).
"""
from __future__ import annotations

from services.blog_media import article_html  # noqa: F401
