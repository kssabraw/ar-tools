"""Website Builder — assembling an Offers / Specials page.

The offers page (reference §5.1, Offers / Specials — ⭐ SOP extension, Writer #12
"thin") is current coupons, seasonal promos and financing. Its required input is
"current offers with terms and expiry" and its defining pitfall is "expired
offers left live" — so every offer is a fact the operator enters, and this module
INVENTS NOTHING:

* the offer cards (title / value / terms / expiry / CTA), the financing block and
  the fine print all pass straight through to `sections` frontmatter, which the
  /specials/ route renders deterministically;
* there is deliberately **no LLM call**. The reference's angle is "clarity over
  hype — the offer, its real value, its terms and expiry, plainly stated", and
  offer value/terms/expiry are legal facts a model must never touch or embellish.
  A short operator intro is used verbatim; nothing else is prose.

So this writer is pure assembly — the offers singleton is one per site at
/specials/, id-addressed like the FAQ (website_content._ID_ADDRESSED_ENTRY_ID).
"""

from __future__ import annotations

from typing import Any


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _offer_cards(offers: dict) -> list[dict]:
    """Normalised offer cards. An offer with no title is dropped (nothing to show).

    Each card carries the reference's fields — title, value, terms, expiry, CTA —
    camelCased for the template. Empty fields are kept as empty strings so the
    route can hide them per-field rather than guessing which are present.
    """
    out: list[dict] = []
    for raw in offers.get("offers") or []:
        if not isinstance(raw, dict):
            continue
        title = _clean(raw.get("title"))
        if not title:
            continue
        out.append(
            {
                "title": title,
                "value": _clean(raw.get("value")),
                "terms": _clean(raw.get("terms")),
                "expiry": _clean(raw.get("expiry")),
                "ctaLabel": _clean(raw.get("cta_label")),
                "ctaHref": _clean(raw.get("cta_href")),
            }
        )
    return out


def _meta_description(offers: dict, cards: list[dict]) -> str:
    """A meta description from the operator intro, else the first offer, trimmed."""
    text = _clean(offers.get("intro"))
    if not text and cards:
        first = cards[0]
        text = " — ".join(p for p in (first["title"], first["value"]) if p)
    text = " ".join(text.split())
    if len(text) <= 160:
        return text
    return text[:160].rsplit(" ", 1)[0].rstrip(",.;:") + "…"


def build_offers_content(offers: dict) -> dict:
    """The `content` dict a website_pages row stores for the offers singleton.

    Pure — mirrors the core-pages/project shape (title / description / body /
    frontmatter.sections). The body stays empty: an offers page is its cards, and
    those are structured `sections` the /specials/ route renders. Sections carried:
    `intro` (verbatim operator lede), `offers` (cards), `financing`, `finePrint`.
    """
    offers = offers or {}
    cards = _offer_cards(offers)

    sections: dict[str, Any] = {}
    intro = _clean(offers.get("intro"))
    if intro:
        sections["intro"] = intro
    if cards:
        sections["offers"] = cards
    financing = _clean(offers.get("financing"))
    if financing:
        sections["financing"] = financing
    fine_print = _clean(offers.get("fine_print"))
    if fine_print:
        sections["finePrint"] = fine_print

    return {
        "title": _clean(offers.get("title")) or "Current Offers",
        "description": _meta_description(offers, cards),
        "body": "",
        "frontmatter": {"sections": sections},
    }
