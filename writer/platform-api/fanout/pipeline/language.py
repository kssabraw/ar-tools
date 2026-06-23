"""Pre-embedding language-ID filter (PRD §7.6 follow-up).

DataForSEO is locked to en/US (`location_code=2840`, `language_code='en'`) but
its related-keyword + autocomplete endpoints occasionally surface non-English
Latin-script phrases when the dominant terms happen to share spelling with
English — e.g. "wat is een managed service provider" (Dutch), "was ist eine
managed service provider" (German), "qué es un managed service provider"
(Spanish). The embedding-cosine relevance gate then accepts them because most
of the string embeds close to its English counterpart, so they slip into the
active pool and the orchestrator.

The filter is a TWO-LAYER signal because either layer alone misses cases the
other catches:

  1. NON-ENGLISH STARTER (curated, deterministic). A regex over the first 1-2
     tokens catches the dominant failure mode: a non-English question/article
     ("wat is een", "was ist eine", "qué es un", "cos'è un", "comment
     fonctionne") wrapping an English noun phrase. lingua alone misclassifies
     these as English because the English noun phrase dominates the string by
     character count; the starter is the signal that doesn't get diluted.

  2. LINGUA LANGUAGE DETECTOR (model, full string). Catches pure-non-English
     keywords that don't begin with a known starter ("fournisseur de services
     gérés", "proveedor de servicios gestionados"). Run at a high confidence
     threshold (`confidence_threshold`, default 0.7) so short ambiguous strings
     ("retatrutide", "best msp") stay in — lingua's confidence on 1-2 word
     inputs is noisy.

A keyword is filtered iff layer 1 OR layer 2 fires. Defensive: any internal
error returns False (= keep), so a misbehaving detector cannot abort a run.
"""

from __future__ import annotations

import logging
import re
from typing import Callable

logger = logging.getLogger(__name__)

# Latin-script languages we expect DataForSEO to leak through. English MUST be
# in the pool — without it lingua would label every keyword as one of the
# non-English candidates. The set is kept deliberately small (faster + sharper
# than the all-176-languages default).
DEFAULT_LANGUAGES: tuple[str, ...] = (
    "ENGLISH", "DUTCH", "GERMAN", "FRENCH", "SPANISH", "PORTUGUESE",
    "ITALIAN", "POLISH", "SWEDISH", "DANISH", "BOKMAL", "FINNISH",
    "INDONESIAN", "TURKISH", "ROMANIAN", "CZECH", "MALAY", "SLOVAK",
    "HUNGARIAN", "TAGALOG",
)


# ----- Layer 1: non-English starter regex ------------------------------------
#
# Curated for low English collision. Two-token patterns are preferred (they
# disambiguate words that exist in English too, like German "was"). Each
# pattern matches at the start of the normalized keyword, whole-word.
#
# Lower-cased; the matcher lower-cases input before testing.

# Two-token starters (high precision — the second token confirms the language).
_TWO_TOKEN_STARTERS = (
    # Dutch
    r"wat\s+(?:is|zijn|betekent|kost|kosten|doet|doen)",
    r"hoe\s+(?:werkt|werken|kan|kun|krijg|krijgt|maak|moet|moeten|veel|lang)",
    r"waarom\s+\w+",
    r"wanneer\s+\w+",
    r"welke\s+\w+",
    r"welk\s+\w+",
    # German
    r"was\s+(?:ist|sind|bedeutet|kostet|kosten|macht|machen|tut)",
    r"wie\s+(?:funktioniert|funktionieren|viel|lange|kann|geht|ist)",
    r"warum\s+\w+",
    r"wieso\s+\w+",
    r"weshalb\s+\w+",
    r"wer\s+(?:ist|sind|hat|war|kann)",
    # French
    r"qu['’\s]?est[- ]ce\s+\w+",
    r"comment\s+(?:fonctionne|fonctionnent|choisir|trouver|faire|utiliser|installer)",
    r"pourquoi\s+\w+",
    r"quand\s+\w+",
    r"quel(?:le|les|s)?\s+(?:est|sont|prix)",
    # Spanish (accented forms = no English collision)
    r"qué\s+(?:es|son|significa|hace|hacen)",
    r"cómo\s+\w+",
    r"cuándo\s+\w+",
    r"dónde\s+\w+",
    r"cuál(?:es)?\s+(?:es|son)",
    r"para\s+qué\b",
    # Italian
    r"cos['’]?\s*è\s+\w+",
    r"cosa\s+(?:è|significa|vuol|sono|sta)",
    r"che\s+cos['’]?\s*è\b",
    r"come\s+(?:funziona|funzionano|scegliere|usare|installare)",
    r"perché\s+\w+",
    r"quanto\s+(?:costa|costano)",
    # Portuguese
    r"o\s+que\s+(?:é|são|significa)\b",
    r"como\s+(?:funciona|funcionam|escolher|usar|instalar)",
    r"por\s+que\b",
    # Polish
    r"co\s+to\s+\w+",
    r"jak\s+(?:działa|wybrać|zrobić|używać)",
    r"dlaczego\s+\w+",
    # Indonesian / Malay
    r"apa\s+(?:itu|yang)\b",
    r"bagaimana\s+\w+",
    r"mengapa\s+\w+",
    # Turkish
    r"nedir\b",  # often a suffix-style keyword: "msp nedir" — caught by single-token below
    r"nasıl\s+\w+",
)

# Single-token starters (used when a two-token match doesn't fire). Restricted
# to words that virtually never appear at the start of an English keyword.
_ONE_TOKEN_STARTERS = (
    # Dutch — high precision (no English collision)
    "wat", "hoe", "waarom", "wanneer", "welke", "welk",
    "een", "het",
    # German — only the accent-free question words that don't collide
    "warum", "wieso", "weshalb", "wozu",
    "welcher", "welches", "welche",
    # French — accented / apostrophe forms
    "pourquoi", "quand",
    "quelle", "quelles", "quels",
    # Spanish — accented forms (the accent is the signal)
    "qué", "cómo", "cuándo", "dónde", "cuál", "cuáles",
    "porqué", "cuántos", "cuántas", "cuánto", "cuánta",
    # Italian — accented
    "perché", "perchè",
    # Polish — accented / unique
    "dlaczego", "kiedy", "gdzie",
)

# Some keywords end in a non-English suffix-style marker rather than starting
# with one (Turkish "nedir", German "bedeutung", etc.). Listed as suffix tokens
# for an end-of-string check.
_NON_ENGLISH_SUFFIX_TOKENS = (
    "nedir",         # Turkish "what is" (used as suffix: "msp nedir")
    "betekenis",     # Dutch "meaning"
    "bedeutung",     # German "meaning"
    "signification", # French "meaning"
    "significado",   # Spanish "meaning"
    "significato",   # Italian "meaning"
)


def _build_starter_pattern() -> re.Pattern[str]:
    one = "|".join(re.escape(w) for w in _ONE_TOKEN_STARTERS)
    two = "|".join(_TWO_TOKEN_STARTERS)
    suf = "|".join(re.escape(w) for w in _NON_ENGLISH_SUFFIX_TOKENS)
    pattern = (
        r"^(?:"
        + two
        + r"|(?:" + one + r")\b"
        + r")"
        + r"|\b(?:" + suf + r")\s*$"
    )
    return re.compile(pattern, re.IGNORECASE | re.UNICODE)


_STARTER_RE = _build_starter_pattern()


def matches_non_english_starter(keyword: str) -> bool:
    """Layer 1: True when the keyword starts (or ends) with a high-precision
    non-English marker. Pure regex, no model dependency, fast."""
    if not keyword:
        return False
    return bool(_STARTER_RE.search(keyword))


# ----- Layer 2: lingua language detector -------------------------------------


def make_language_filter(
    confidence_threshold: float = 0.7,
    languages: tuple[str, ...] = DEFAULT_LANGUAGES,
    *,
    require_min_words: int = 3,
) -> Callable[[str], bool] | None:
    """Build a `(keyword) -> bool` filter (True = drop as non-English).

    Layered: the starter regex (layer 1) runs first; if it matches, the keyword
    is filtered without invoking lingua. Otherwise, lingua scores the full
    string (layer 2). The model has poor precision on 1-2 word inputs, so it's
    only consulted for keywords with at least `require_min_words` tokens.

    Returns None if `lingua` is unavailable or fails to initialize, so the
    caller can skip layer 2 cleanly. Layer 1 is then unused too — callers
    treat the absence of a filter as "language gating off" rather than
    silently degrading to the starter-only check (cleaner kill-switch).
    """
    try:
        from lingua import Language, LanguageDetectorBuilder
    except ImportError:
        logger.warning(
            "language_filter_unavailable",
            extra={"event": "language_filter_unavailable",
                   "reason": "lingua not installed"},
        )
        return None

    try:
        lang_enum = [getattr(Language, name) for name in languages]
        if not any(lang.name == "ENGLISH" for lang in lang_enum):
            raise ValueError("language pool must include ENGLISH")
        detector = LanguageDetectorBuilder.from_languages(*lang_enum).build()
        english = Language.ENGLISH
    except Exception as exc:  # noqa: BLE001 — build failure -> skip the gate
        logger.warning(
            "language_filter_build_failed",
            extra={"event": "language_filter_build_failed", "reason": repr(exc)},
        )
        return None

    def is_non_english(keyword: str) -> bool:
        if not keyword:
            return False
        # Layer 1: deterministic starter / suffix check.
        if matches_non_english_starter(keyword):
            return True
        # Layer 2: lingua, only on long-enough strings (the model is too noisy
        # on 1-2 word inputs — see PR notes / language.py docstring).
        if len(keyword.split()) < require_min_words:
            return False
        try:
            confidences = detector.compute_language_confidence_values(keyword)
        except Exception:  # noqa: BLE001 — never abort the gate
            return False
        if not confidences:
            return False
        top = confidences[0]
        if top.language == english:
            return False
        return float(top.value) >= confidence_threshold

    return is_non_english
