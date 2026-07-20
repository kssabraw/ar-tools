"""Brand → visual signal for media planning.

Per the owner decision, only the brand *personality* is fed to the media planner
(the rest of the brand voice is copywriting guidance the image model can't use).
`extract_brand_personality` distills the `personality` arrays from the stored
brand voice into one deduped line. Pure.
"""
from __future__ import annotations

_DEFAULT = "professional, clear, and credible"


def extract_brand_personality(brand_voice: dict | None) -> str:
    """One comma-joined personality line from the client's brand voice.

    Pulls `current_voice.personality` + `recommended_voice.personality` (each a
    list of short trait strings), lowercases + dedupes preserving order, and
    joins. Falls back to a neutral default when nothing is on file, so the
    planner always gets a usable steer."""
    traits: list[str] = []
    seen: set[str] = set()
    if isinstance(brand_voice, dict):
        for key in ("current_voice", "recommended_voice"):
            voice = brand_voice.get(key)
            if not isinstance(voice, dict):
                continue
            for trait in voice.get("personality") or []:
                t = str(trait).strip().rstrip(".")
                low = t.lower()
                if t and low not in seen:
                    seen.add(low)
                    traits.append(t)
    if not traits:
        return _DEFAULT
    # Lowercase the joined line for a consistent prompt register.
    return ", ".join(traits).lower()
