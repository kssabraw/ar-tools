"""Distinctiveness directive — the write-time mirror of the hardened voice judge.

The voice scorecard's heaviest honest signal is `distinctiveness`: could this be
published on a competitor's site by swapping the brand name? The page generators
carry that instruction in `voice_card.render_voice_card_block`; the blog/service
article writer hand-rolls its voice block in three separate places (intro,
sections, conclusion), so this shared helper renders the same directive once and
each site appends it — the seam those three files never had.

Pure + unit-tested. Mirrors the copy owner-approved for the page generators
(PR #759), adapted from "page" to "article".
"""

from __future__ import annotations

from typing import Optional

from models.writer import BrandVoiceCard


def distinctiveness_directive(card: Optional[BrandVoiceCard]) -> str:
    """The name-swap directive plus this client's distinctive raw material.

    Empty string when there is no card. The directive paragraph always renders
    for a card (it leans on the differentiators / audience material elsewhere in
    the same prompt); the two field lines render only when the card carries them.
    Leads with a blank line so it separates cleanly when appended to a prompt
    part list joined by newlines."""
    if card is None:
        return ""
    lines = [
        "\nDISTINCTIVENESS — write as unmistakably this client. This article is scored on one",
        "test above all: could it be published on a competitor's site by swapping the brand",
        "name? If yes, it fails. Generic, competent copy is a failure here, not a pass. Lead",
        "with what only this client can say — their specific proof, differentiators, and this",
        "reader's exact concerns — never generic benefit-claims any competitor could make.",
    ]
    if card.differentiators:
        lines.append(
            "Differentiators to foreground (don't just list them): "
            + "; ".join(card.differentiators)
        )
    if card.signature_phrases:
        lines.append(
            "This brand's own words (use where they fit naturally, never forced): "
            + " / ".join(f'"{p}"' for p in card.signature_phrases)
        )
    return "\n".join(lines)
