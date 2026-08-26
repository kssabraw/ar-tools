"""Extract OWNER / MANAGER names from a business website's HTML. PURE.

This is the fallback for when Outscraper enrichment comes back with no NAME (status `no_contacts`,
or contacts that carry an email/phone but nobody's name). It reads the prospect's OWN site — a free
own-HTTP-GET, the `scan_tech` posture — and pulls the person a caller should ask for.

**Deterministic and fact-grounded, the heatmap/tech-signal discipline.** A name is extracted ONLY
when it is tied to an explicit ownership/management ROLE (`owner`, `founder`, `president`,
`principal`, `proprietor`, `manager`, …) or carried by schema.org structured data (`founder` /
`employee` with a matching `jobTitle`). We NEVER lift "a capitalised phrase that looks like a name"
off a page — that manufactures a contact, which is the exact failure the module keeps meeting. The
bar is deliberately high: this is a caller-facing name, and a wrong one ("Hi, is Jane the owner
there?" — "who?") costs the call.

**The invariants this module carries:**

  * **One-directional business-name rejection (I-099 / `detect_ai_mention`).** A candidate person
    name that IS the business (its tokens are the business's, or a generic trade word) is dropped —
    "Acme Plumbing, Family Owned" must not yield a person called "Acme Plumbing". The check fails
    toward a MISS.
  * **Role-anchored, name is the free variable.** The ROLE keyword is the fixed anchor; the NAME is
    read off it. A bare Title-Case phrase with no role nearby is nothing.
  * **Evidence is replayable.** Every extracted name keeps the matched snippet (or the JSON-LD
    fragment) in `evidence`, so a finding can be re-checked from stored inputs.

The producer (`name_scrape.py`) owns the network + which pages to read; this module never fetches.
"""

from __future__ import annotations

import html as _html
import json
import re
from dataclasses import dataclass, field
from typing import Any

# --- role vocabulary -------------------------------------------------------------------------
#
# Each entry: the surface form(s) as they appear on a page → the canonical title we store. Ordered
# longest-first so "co-owner" wins over "owner" and "president & ceo" over "president". These are
# OWNERSHIP / SENIOR-MANAGEMENT roles only — an "employee" or a "plumber" jobTitle is not a contact
# this fallback is for.

_ROLE_CANON: tuple[tuple[str, str], ...] = (
    (r"owner\s*/\s*operator", "Owner/Operator"),
    (r"owner\s*(?:and|&|-)\s*operator", "Owner/Operator"),
    (r"co[-\s]?owner", "Co-Owner"),
    (r"business\s+owner", "Owner"),
    (r"owner", "Owner"),
    (r"co[-\s]?founder", "Co-Founder"),
    (r"founder", "Founder"),
    (r"president\s*(?:and|&)\s*ceo", "President & CEO"),
    (r"president", "President"),
    (r"vice\s+president", "Vice President"),
    (r"chief\s+executive\s+officer", "CEO"),
    (r"chief\s+operating\s+officer", "COO"),
    (r"chief\s+financial\s+officer", "CFO"),
    (r"ceo", "CEO"),
    (r"managing\s+director", "Managing Director"),
    (r"managing\s+partner", "Managing Partner"),
    (r"principal", "Principal"),
    (r"proprietor", "Proprietor"),
    (r"director\s+of\s+operations", "Director of Operations"),
    (r"general\s+manager", "General Manager"),
    (r"operations\s+manager", "Operations Manager"),
    (r"office\s+manager", "Office Manager"),
    (r"manager", "Manager"),
    (r"partner", "Partner"),
)

# The subset a role may anchor a name WITHOUT punctuation between them ("Owner John Smith"). Kept
# strong because a bare "manager john" / "partner john" is far likelier to be prose than a byline;
# the weaker roles need a comma/colon/"our"/"is our" to fire.
#
# President / CEO / Principal are DELIBERATELY EXCLUDED from the loose form: "President Joe Biden" /
# "CEO Tim Cook" / "Principal Jane Doe" name people of OTHER entities all over ordinary prose
# (testimonials, chamber-of-commerce mentions, industry figures, schools), so the punctuation-free
# "<role> <Name>" byline is a false-positive magnet for them. They still fire on every PUNCTUATED
# form ("Jane Doe, President", "President: Jane Doe", "our President Jane Doe"), which is how a real
# business page actually credits them — only the bare loose form is withheld. Owner / Founder /
# Proprietor read as the business's own byline in the loose form far more reliably.
_STRONG_ROLES = frozenset(
    {"Owner", "Owner/Operator", "Co-Owner", "Founder", "Co-Founder", "Proprietor"}
)

_ROLE_ALT = "|".join(f"(?:{pat})" for pat, _ in _ROLE_CANON)
_STRONG_ALT = "|".join(
    f"(?:{pat})" for pat, canon in _ROLE_CANON if canon in _STRONG_ROLES
)

# A person name: 2–3 Title-Case tokens. A token is a capital followed by EITHER a lone "." (a middle
# initial, "A.") OR letters/apostrophe/hyphen that END IN A LETTER — so trailing sentence
# punctuation ("Bill Murphy.") is left out of the name. Deliberately NOT one token (too many false
# positives) and not >3 (a sentence, not a name).
_NAME_TOKEN = r"[A-Z](?:\.|[A-Za-z'’\-]*[A-Za-z'’])"
_NAME = rf"{_NAME_TOKEN}(?:\s+{_NAME_TOKEN}){{1,2}}"

# Tokens that disqualify a "name" — nav chrome, page words, and generic business/trade words a
# masquerading business name would carry. Lower-cased comparison. This is the anti-fabrication
# stoplist: better to miss a real name than to record "Contact Us" or "Emergency Plumbing" as a
# person.
_NAME_STOPWORDS = frozenset(
    {
        # nav / page chrome
        "home", "about", "contact", "us", "our", "team", "services", "service", "menu",
        "reviews", "review", "gallery", "blog", "news", "faq", "faqs", "careers", "quote",
        "book", "booking", "appointment", "call", "today", "now", "welcome", "meet", "staff",
        "testimonials", "testimonial", "privacy", "policy", "terms", "sitemap", "login",
        "read", "more", "learn", "get", "started", "free", "estimate", "estimates",
        # generic business / legal
        "company", "business", "family", "owned", "operated", "llc", "inc", "incorporated",
        "corp", "co", "ltd", "group", "enterprises", "solutions", "brothers", "sons",
        "professional", "professionals", "experts", "expert", "specialists", "specialist",
        # common local trades (a business name masquerading as a person)
        "plumbing", "plumber", "roofing", "roofer", "electric", "electrical", "electrician",
        "hvac", "heating", "cooling", "air", "conditioning", "landscaping", "landscape",
        "cleaning", "cleaners", "painting", "painters", "construction", "contractors",
        "contractor", "remodeling", "restoration", "pest", "control", "dental", "dentist",
        "law", "legal", "attorney", "attorneys", "insurance", "realty", "real", "estate",
        "auto", "automotive", "repair", "towing", "flooring", "concrete", "fence", "fencing",
        "garage", "door", "doors", "window", "windows", "roof", "tree", "lawn", "pool",
    }
)

# Words that are roles/titles themselves — a "name" token equal to one of these is prose bleed
# ("Owner Operated"), not a person.
_ROLE_WORDS = frozenset(
    {
        "owner", "co-owner", "operator", "founder", "co-founder", "president", "vice",
        "ceo", "coo", "cfo", "manager", "managing", "director", "principal", "proprietor",
        "partner", "chief", "executive", "operating", "financial", "officer", "general",
        "operations", "office",
    }
)


@dataclass(frozen=True)
class ExtractedName:
    """One owner/manager the extractor is confident enough to surface. `source_kind` records HOW it
    was found (`jsonld` = structured data, `text` = a role-anchored sentence) — the report and the
    caller weight a scraped name by that, and it is kept for replay alongside `evidence`."""

    full_name: str
    title: str
    source_kind: str  # "jsonld" | "text"
    evidence: str
    first_name: str | None = None
    last_name: str | None = None

    def as_contact(self) -> dict[str, Any]:
        """The name/title fields of a `prospect_contact` row (the queue adds join keys + source)."""
        return {
            "full_name": self.full_name,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "title": self.title,
        }


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _key(name: str) -> str:
    return _norm(name).lower()


def _split_name(full: str) -> tuple[str | None, str | None]:
    parts = [p for p in _norm(full).split(" ") if p]
    if not parts:
        return None, None
    if len(parts) == 1:
        return parts[0], None
    return parts[0], parts[-1]


def _business_tokens(business_name: str | None) -> frozenset[str]:
    if not business_name:
        return frozenset()
    return frozenset(re.findall(r"[a-z0-9]+", business_name.lower()))


def is_plausible_name(name: str, *, business_tokens: frozenset[str]) -> bool:
    """Whether a candidate string is a real person's name we'd surface. Conservative by design.

    Rejects: fewer than two tokens, any token in the nav/business stoplist, any token that is itself
    a role word, and a candidate that IS the business (all of its significant tokens are the
    business's — the one-directional business-name rejection, I-099). Pure + independently testable.
    """
    tokens = [t for t in _norm(name).split(" ") if t]
    if len(tokens) < 2 or len(tokens) > 3:
        return False
    lowers = [re.sub(r"[.’']", "", t.lower()).strip("-") for t in tokens]
    for low in lowers:
        if not low:
            return False
        if low in _NAME_STOPWORDS or low in _ROLE_WORDS:
            return False
        # a lone initial ("j") is fine as a middle token but a name of only initials is not
    # Every significant (non-initial) token being a business token ⇒ this is the business, not a
    # person. Single-letter tokens (initials) don't count toward "significant".
    significant = [low for low in lowers if len(low) > 1]
    if significant and business_tokens and all(low in business_tokens for low in significant):
        return False
    # Require at least two multi-letter tokens — "J. B" or "A B" is not enough to dial.
    if len([low for low in lowers if len(low) > 1]) < 2:
        return False
    return True


def _canonical_title(role_text: str) -> str:
    """Map a matched role surface form to its canonical title. Longest-form-first, so the first
    entry whose pattern spans the whole matched text wins."""
    low = _norm(role_text).lower()
    for pat, canon in _ROLE_CANON:
        if re.fullmatch(pat, low, re.I):
            return canon
    # Fallback: title-case what matched (a partial like "senior manager" collapsing to "manager"
    # still stores something legible). Should be rare — the alternation is built from these forms.
    return " ".join(w.capitalize() for w in low.split())


# --- text patterns ---------------------------------------------------------------------------
#
# Each fires (name, role) or (role, name) with the name as the free variable anchored by the role.
# The role + connector literals are case-INSENSITIVE (inline `(?i:…)`) but the NAME matcher stays
# case-SENSITIVE — a global `re.I` would make its `[A-Z]` match lowercase, so "owner of the shop"
# would read "of the shop" as a name. The canonicaliser normalises the role. The strong-role loose
# form is the only one allowed WITHOUT punctuation between role and name.

_ROLE_I = f"(?i:{_ROLE_ALT})"
_STRONG_I = f"(?i:{_STRONG_ALT})"

_PAT_NAME_COMMA_ROLE = re.compile(
    rf"\b({_NAME})\s*[,–—\-|]\s*(?i:the\s+|our\s+|a\s+)?({_ROLE_I})\b"
)
_PAT_ROLE_COLON_NAME = re.compile(
    rf"\b({_ROLE_I})\s*[:–—\-]\s+({_NAME})"
)
_PAT_NAME_IS_ROLE = re.compile(
    rf"\b({_NAME})\s+(?i:is|as)\s+(?i:the\s+|our\s+|a\s+|one\s+of\s+the\s+)?({_ROLE_I})\b"
)
_PAT_MEET_ROLE_NAME = re.compile(
    rf"\b(?i:meet|our|by)\s+(?i:our\s+)?({_ROLE_I})[,:]?\s+({_NAME})"
)
_PAT_STRONG_ROLE_NAME = re.compile(
    rf"\b({_STRONG_I})\s*[,:]?\s+({_NAME})"
)


def html_to_text(html: str | None) -> str:
    """A crude, dependency-free visible-text projection of a page. Pure.

    Drops script/style/noscript blocks, replaces tags with spaces (so `<b>John</b> Smith` reads as
    two words, not "JohnSmith"), and unescapes entities. Not a parser — enough to run role-anchor
    regexes over prose without a token running into the next tag's."""
    text = html or ""
    text = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = _html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _add(
    out: list[ExtractedName], seen: dict[str, int], name: str, title: str,
    source_kind: str, evidence: str,
) -> None:
    """Add a candidate, de-duped by normalised name. A later STRUCTURED (jsonld) hit upgrades a text
    hit's provenance; otherwise first-seen wins (its evidence is kept)."""
    key = _key(name)
    if not key:
        return
    if key in seen:
        idx = seen[key]
        if source_kind == "jsonld" and out[idx].source_kind != "jsonld":
            out[idx] = ExtractedName(
                full_name=out[idx].full_name, title=out[idx].title, source_kind="jsonld",
                evidence=evidence, first_name=out[idx].first_name, last_name=out[idx].last_name,
            )
        return
    first, last = _split_name(name)
    seen[key] = len(out)
    out.append(
        ExtractedName(
            full_name=_norm(name), title=title, source_kind=source_kind,
            evidence=_norm(evidence)[:300], first_name=first, last_name=last,
        )
    )


def _extract_text(text: str, *, business_tokens: frozenset[str],
                  out: list[ExtractedName], seen: dict[str, int]) -> None:
    patterns = (
        (_PAT_NAME_COMMA_ROLE, 0, 1),   # (name_group, role_group)
        (_PAT_ROLE_COLON_NAME, 1, 0),
        (_PAT_NAME_IS_ROLE, 0, 1),
        (_PAT_MEET_ROLE_NAME, 1, 0),
        (_PAT_STRONG_ROLE_NAME, 1, 0),
    )
    for pat, name_grp, role_grp in patterns:
        for m in pat.finditer(text):
            name = m.group(name_grp + 1)
            role = m.group(role_grp + 1)
            if not is_plausible_name(name, business_tokens=business_tokens):
                continue
            _add(out, seen, name, _canonical_title(role), "text", m.group(0))


# --- JSON-LD ---------------------------------------------------------------------------------

_JSONLD_BLOCK = re.compile(
    r'(?is)<script[^>]+type\s*=\s*["\']application/ld\+json["\'][^>]*>(.*?)</script>'
)
# schema.org relations that imply ownership/authorship of the business.
_OWNER_RELATIONS = ("founder", "founders")
_STAFF_RELATIONS = ("employee", "employees", "member", "members")


# A depth bound on the JSON-LD walk so a maliciously (or accidentally) deep structure can't blow the
# recursion limit — `extract_names` promises never to raise, and the producer treats a raise as a
# per-prospect failure. Real schema.org graphs are a handful of levels deep.
_JSONLD_MAX_DEPTH = 200


def _iter_json_nodes(node: Any, _depth: int = 0):
    if _depth > _JSONLD_MAX_DEPTH:
        return
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _iter_json_nodes(value, _depth + 1)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_json_nodes(item, _depth + 1)


def _person_name(node: Any) -> str | None:
    if not isinstance(node, dict):
        return None
    name = node.get("name")
    if isinstance(name, str) and _norm(name):
        return _norm(name)
    given, family = node.get("givenName"), node.get("familyName")
    if isinstance(given, str) and isinstance(family, str):
        joined = _norm(f"{given} {family}")
        return joined or None
    return None


def _job_title(node: Any) -> str | None:
    for key in ("jobTitle", "roleName", "title"):
        val = node.get(key) if isinstance(node, dict) else None
        if isinstance(val, str) and _norm(val):
            return _norm(val)
    return None


def _title_is_role(title: str | None) -> str | None:
    """The canonical title if `title` names an ownership/management role we accept, else None."""
    if not title:
        return None
    low = title.lower()
    for pat, canon in _ROLE_CANON:
        if re.search(rf"\b(?:{pat})\b", low, re.I):
            return canon
    return None


def _extract_jsonld(html: str, *, business_tokens: frozenset[str],
                    out: list[ExtractedName], seen: dict[str, int]) -> None:
    for block in _JSONLD_BLOCK.findall(html or ""):
        raw = _html.unescape(block).strip()
        try:
            data = json.loads(raw)
        except (ValueError, TypeError, RecursionError):
            # Malformed OR pathologically deep — either way, skip this block. extract_names must
            # never raise (the producer treats a raise as a per-prospect failure).
            continue
        for node in _iter_json_nodes(data):
            if not isinstance(node, dict):
                continue
            # A relation (founder/employee) hanging off an org: the relation implies the role for
            # founders; staff must carry a matching jobTitle to count.
            for rel in _OWNER_RELATIONS:
                for person in _as_list(node.get(rel)):
                    name = _person_name(person)
                    if not name or not is_plausible_name(name, business_tokens=business_tokens):
                        continue
                    title = _title_is_role(_job_title(person)) or "Founder"
                    _add(out, seen, name, title, "jsonld", f"schema.org {rel}: {name}")
            for rel in _STAFF_RELATIONS:
                for person in _as_list(node.get(rel)):
                    name = _person_name(person)
                    title = _title_is_role(_job_title(person))
                    if not title or not name:
                        continue
                    if not is_plausible_name(name, business_tokens=business_tokens):
                        continue
                    _add(out, seen, name, title, "jsonld", f"schema.org {rel}: {name} ({title})")
            # A standalone Person node whose own jobTitle names an ownership role.
            if _is_type(node, "Person"):
                name = _person_name(node)
                title = _title_is_role(_job_title(node))
                if name and title and is_plausible_name(name, business_tokens=business_tokens):
                    _add(out, seen, name, title, "jsonld", f"schema.org Person: {name} ({title})")


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _is_type(node: dict, wanted: str) -> bool:
    t = node.get("@type")
    if isinstance(t, str):
        return t.lower() == wanted.lower()
    if isinstance(t, list):
        return any(isinstance(x, str) and x.lower() == wanted.lower() for x in t)
    return False


def extract_names(
    html: str | None, *, business_name: str | None = None, max_names: int = 8
) -> list[ExtractedName]:
    """Owner/manager names from one page's HTML. Pure — never fetches, never raises.

    JSON-LD first (structured, higher confidence), then role-anchored text. De-duped by name; a
    structured hit upgrades a text hit's provenance. Returns [] for a page that carries no
    role-anchored name — a genuine "read the site, nobody named" (the producer records that
    distinctly from a failed fetch).
    """
    if not html:
        return []
    business_tokens = _business_tokens(business_name)
    out: list[ExtractedName] = []
    seen: dict[str, int] = {}
    _extract_jsonld(html, business_tokens=business_tokens, out=out, seen=seen)
    _extract_text(html_to_text(html), business_tokens=business_tokens, out=out, seen=seen)
    return out[:max_names]


def merge_names(*groups: list[ExtractedName], max_names: int = 8) -> list[ExtractedName]:
    """Fold several pages' extractions into one de-duped list, preserving order and jsonld-upgrade
    (the producer scans several pages; the homepage's hits come first). Pure."""
    out: list[ExtractedName] = []
    seen: dict[str, int] = {}
    for group in groups:
        for name in group:
            _add(out, seen, name.full_name, name.title, name.source_kind, name.evidence)
            # carry the split names / exact fields through the merge
            idx = seen[_key(name.full_name)]
            if out[idx].first_name is None and name.first_name is not None:
                out[idx] = ExtractedName(
                    full_name=out[idx].full_name, title=out[idx].title,
                    source_kind=out[idx].source_kind, evidence=out[idx].evidence,
                    first_name=name.first_name, last_name=name.last_name,
                )
    return out[:max_names]
