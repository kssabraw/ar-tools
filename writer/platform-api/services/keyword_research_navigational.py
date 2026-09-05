"""Keyword Research — navigational + competitor-brand filter.

The audience filter answers "would our BUYER search this?" but a keyword can be
on-topic AND buyer-adjacent AND still be a useless content target because its
intent is NAVIGATIONAL — someone looking up a specific company's contact details
or logging into a portal. On a live BSA Claims run seeded on buyer terms, the #2
keyword by volume was "sedgwick phone number" (27,100) — a *claimant trying to
reach a competitor about their claim*, not a carrier researching a TPA, and never
a blog post BSA would write.

Two layers:

  * a UNIVERSAL navigational-intent guard — a curated support/lookup vocabulary
    ("phone number", "customer service", "login", "claim status", "tracking
    number", …) that is never a content-SEO target for a B2B services business,
    regardless of which brand it's attached to (so it catches "gallagher bassett
    phone number" even though Gallagher Bassett isn't a registered competitor).
  * a COMPETITOR-BRAND guard — keywords dominated by a known competitor's brand
    name (from the client's competitor registry), EXCEPT comparison / research
    keywords ("sedgwick alternatives", "sedgwick vs crawford") which are exactly
    the competitor content a challenger SHOULD write. Brand matchers are built
    conservatively (industry-generic + geographic words stripped; a bare generic
    remainder like "florida" contributes no matcher) so the guard can't nuke the
    run's own topic.

Both best-effort and pure (the registry read is the only I/O), unit-tested.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import keyword_research

logger = logging.getLogger(__name__)

# Support / lookup / account intent — never a B2B content-SEO target whatever the
# brand. Matched as whole words / phrases against the normalized keyword.
_NAVIGATIONAL_TERMS = (
    "phone number", "phone no", "telephone number",
    "customer service", "customer service number", "customer support",
    "contact number", "contact info", "toll free number", "800 number",
    "login", "log in", "log on", "logon", "sign in", "signin",
    "portal", "portal login", "member login", "member portal", "customer portal",
    "client portal", "employee portal", "provider portal", "patient portal",
    "my account", "account login",
    "claim status", "claims status", "check claim status", "claim number",
    "tracking number", "track my claim", "track claim",
    "email address", "mailing address", "corporate office", "fax number",
    "hours of operation", "customer service hours",
)
_NAVIGATIONAL_RE = None  # built lazily below

# Comparison / research intent that RESCUES a competitor-brand keyword — a
# challenger WANTS to rank for "sedgwick alternatives" / "sedgwick vs crawford".
_COMPARISON_TERMS = (
    "vs", "versus", "compare", "comparison", "alternative", "alternatives",
    "competitor", "competitors", "review", "reviews", "better than", "or",
)

# Industry-generic + corporate + geographic words stripped from competitor names
# before deriving a distinctive brand matcher (so "Sedgwick Claims Management
# Services" → {sedgwick}, and a name that reduces to only generic/geo words
# contributes no matcher). Tokens are the tokenizer's normalized (trailing-s
# trimmed) forms.
_GENERIC_BRAND_WORDS = {
    "claim", "management", "service", "adjuster", "adjusting", "public",
    "insurance", "insurer", "associate", "firm", "llc", "inc", "incorporated",
    "company", "co", "group", "consultant", "consulting", "national",
    "nationwide", "american", "america", "usa", "best", "premier",
    "professional", "solution", "partner", "tpa", "administrator",
    "administration", "agency", "corp", "corporation", "holding",
    # geographic (state / common city) — never distinctive enough to match on.
    "florida", "fl", "jacksonville", "texas", "tx", "california", "ca",
    "georgia", "orlando", "tampa", "miami", "atlanta", "houston", "dallas",
    "new", "york", "city",
}


def _phrase_regex(terms) -> re.Pattern:
    parts = sorted((re.escape(t) for t in terms), key=len, reverse=True)
    return re.compile(r"\b(?:" + "|".join(parts) + r")\b", re.I)


_NAVIGATIONAL_RE = _phrase_regex(_NAVIGATIONAL_TERMS)
_COMPARISON_RE = _phrase_regex(_COMPARISON_TERMS)

# US state postal abbreviations + street-type words, for the address guard. A
# keyword that is really a street address ("190 bowery new york ny 10012") is
# never a content-SEO target. (Some abbreviations — in / or / me — are dropped by
# the tokenizer as stopwords; that only costs coverage, never correctness.)
_US_STATE_ABBR = frozenset(
    "al ak az ar ca co ct de fl ga hi id il in ia ks ky la me md ma mi mn ms mo "
    "mt ne nv nh nj nm ny nc nd oh ok or pa ri sc sd tn tx ut vt va wa wv wi wy dc".split()
)
_STREET_TYPES = frozenset(
    "st street ave avenue rd road blvd boulevard ln lane dr drive ct court way pl "
    "place ste suite unit apt hwy highway pkwy parkway cir circle ter terrace".split()
)


# ---------------------------------------------------------------------------
# Pure helpers — independently unit-tested.
# ---------------------------------------------------------------------------
def is_navigational(keyword: Optional[str]) -> bool:
    """Whether a keyword reads as navigational / support / account-lookup intent —
    the universal non-content class for a B2B services business. Pure."""
    return bool(_NAVIGATIONAL_RE.search(keyword_research.normalize_keyword(keyword)))


def is_comparison(keyword: Optional[str]) -> bool:
    """Whether a keyword carries comparison / research intent (rescues a
    competitor-brand keyword). Pure."""
    return bool(_COMPARISON_RE.search(keyword_research.normalize_keyword(keyword)))


def is_address(keyword: Optional[str]) -> bool:
    """Whether a keyword is really a street address / location string — a
    navigational lookup for one place, never a content-SEO target ("190 bowery new
    york ny 10012", "123 main street"). Conservative by design (precise over
    broad): matches on a US "<state> <zip>" tail, or a leading street number paired
    with a street-type word or an explicit state+zip — so "24 hour plumber" and
    "50000 btu heater" (a leading number with no address signal) are NOT flagged.
    Pure."""
    toks = keyword_research.tokenize(keyword or "")
    if not toks:
        return False
    # "<state> <zip>" adjacency — an unambiguous US address tail.
    for a, b in zip(toks, toks[1:]):
        if a in _US_STATE_ABBR and len(b) == 5 and b.isdigit():
            return True
    # A leading street number ("190 …") plus an explicit address signal.
    if not (toks[0].isdigit() and len(toks[0]) <= 6):
        return False
    rest = set(toks[1:])
    has_zip = any(len(t) == 5 and t.isdigit() for t in toks[1:])
    return bool(rest & _STREET_TYPES) or (bool(rest & _US_STATE_ABBR) and has_zip)


def brand_matchers(competitors: list[dict]) -> list[set[str]]:
    """The distinctive brand token-sets for a client's competitors — each a set of
    significant tokens that, when ALL present in a keyword, mark it as that
    competitor's brand. Industry-generic + geographic words are stripped; a name
    that reduces to a single short/generic token contributes no matcher (so the
    guard can't nuke the run's own topic). Pure."""
    matchers: list[set[str]] = []
    for c in competitors or []:
        # The NAME token-set — a keyword matches when ALL its distinctive tokens are
        # present (so "gold star adjusters reviews" ⊇ {gold, star}).
        toks = {t for t in keyword_research.token_set(c.get("name"))
                if t not in _GENERIC_BRAND_WORDS}
        if toks:
            # A single-token matcher must be distinctive (long, not generic/geo) so a
            # bare "florida"/"gold" can't match broadly; multi-token sets are safe.
            if not (len(toks) == 1 and len(next(iter(toks))) < 6):
                matchers.append(toks)
        # The DOMAIN label as a SEPARATE single-token matcher (an alternative, not an
        # extra required token) — e.g. "sedgwick" from sedgwick.com.
        m = re.match(r"(?:www\.)?([a-z0-9-]+)\.", (c.get("domain") or "").lower())
        if m:
            label = m.group(1)
            if label not in _GENERIC_BRAND_WORDS and len(label) >= 6 and "-" not in label:
                matchers.append({label})
    return matchers


def is_competitor_brand(keyword: Optional[str], matchers: list[set[str]]) -> bool:
    """Whether a keyword is dominated by a competitor's brand. A match is either:

    * exact — ALL of a matcher's tokens are present as tokens in the keyword
      ("gold star adjusters reviews" ⊇ {gold, star}); or
    * glued — a SINGLE distinctive brand label (≥6 chars — every single-token
      matcher is built that way) appears as a substring of one of the keyword's
      tokens ("mysedgwick portal" → the token "mysedgwick" contains "sedgwick").
      This catches the run-together brand forms exact-token matching misses.

    The glued rule is single-token-only and ≥6-char-gated so a distinctive label
    ("sedgwick") can't collide with an ordinary word; multi-token name matchers
    stay exact (no substring), so "gold" alone never matches. Pure."""
    kt = keyword_research.token_set(keyword)
    if not kt:
        return False
    for m in matchers:
        if not m:
            continue
        if m <= kt:
            return True
        if len(m) == 1:
            (label,) = tuple(m)
            if len(label) >= 6 and any(label in t and t != label for t in kt):
                return True
    return False


def classify_intent(
    keyword: Optional[str], matchers: list[set[str]]
) -> str:
    """Intent tag: 'navigational' > 'competitor' (unless comparison) > 'keep'. Pure."""
    if is_navigational(keyword):
        return "navigational"
    if is_competitor_brand(keyword, matchers) and not is_comparison(keyword):
        return "competitor"
    return "keep"


def apply_navigational(
    rows: list[dict],
    matchers: list[set[str]],
    *,
    drop_competitor: bool = True,
    drop: bool = True,
) -> tuple[list[dict], dict]:
    """Tag every row with ``intent_fit`` and (when ``drop``) remove navigational and
    (when ``drop_competitor``) competitor-brand rows. Returns (kept, report). Pure."""
    kept: list[dict] = []
    dropped_nav = dropped_comp = 0
    for r in rows:
        tag = classify_intent(r.get("keyword"), matchers)
        r = {**r, "intent_fit": tag}
        if tag == "navigational" and drop:
            dropped_nav += 1
        elif tag == "competitor" and drop and drop_competitor:
            dropped_comp += 1
        else:
            kept.append(r)
    report = {
        "gate": "navigational" if (dropped_nav or dropped_comp) else "none",
        "input": len(rows), "kept": len(kept),
        "dropped_navigational": dropped_nav, "dropped_competitor": dropped_comp,
    }
    return kept, report


# ---------------------------------------------------------------------------
# Registry read (I/O) — best-effort.
# ---------------------------------------------------------------------------
def get_client_competitors(client_id: str) -> list[dict]:
    """Active competitors from the client's registry ({name, domain}). Best-effort."""
    try:
        rows = (get_supabase().table("client_competitors")
                .select("name, domain").eq("client_id", client_id).eq("active", True)
                .limit(50).execute()).data or []
        return [r for r in rows if r.get("name") or r.get("domain")]
    except Exception as exc:  # noqa: BLE001
        logger.warning("keyword_research_navigational.competitors_failed",
                       extra={"error": str(exc)})
        return []


def filter_navigational(rows: list[dict], client_id: str) -> tuple[list[dict], dict]:
    """Full navigational + competitor-brand filter. Best-effort — degrades to the
    universal navigational guard when the competitor registry can't be read; the
    whole filter is skipped when disabled by config."""
    if not settings.keyword_research_navigational_filter:
        return rows, {"gate": "off"}
    drop_comp = settings.keyword_research_competitor_filter
    matchers = brand_matchers(get_client_competitors(client_id)) if drop_comp else []
    return apply_navigational(rows, matchers, drop_competitor=drop_comp)
