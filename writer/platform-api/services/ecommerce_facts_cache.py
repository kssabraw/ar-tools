"""Cache for the ecommerce writer's invariant public-spec research.

The nlp-api writer researches the publicly-documented, invariant properties of a
product/compound (CAS number, molecular weight/formula, InChI/SMILES, sequence,
solubility, reconstitution, storage) via a bounded web-search pass. On a
reference reoptimize that cost $0.372 — 31% of the whole run — and 1m24s of wall
clock, and it re-ran from scratch every time the same product was reoptimized.
The values are invariant by definition, so a repeat is pure waste.

This cache lives in platform-api rather than beside the research because
**nlp-api has no database** (no supabase dependency, no Supabase env). The flow
is therefore: platform looks the facts up → passes them on the nlp request →
nlp skips its own research when they are supplied. On a miss nlp researches
exactly as before and platform stores what comes back off the result it already
persists, so a cache outage degrades to today's behaviour rather than failing a
page.

Keyed GLOBALLY on a normalized compound name — a CAS number does not depend on
who sells the compound. Empty results are never cached: a compound we found
nothing for must be re-researched later, not permanently gated.

Pure helpers (`normalize_entity_key`, `is_fresh`, `cache_row`) are unit-tested in
`tests/test_ecommerce.py`; the Supabase round-trips below are best-effort and
never raise.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from config import settings
from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

_TABLE = "ecommerce_public_facts"

# Commercial intent words a store keyword carries that say nothing about WHICH
# compound it is ("Buy L Carnitine" and "L-Carnitine" are the same molecule),
# plus packaging nouns, which describe the pack rather than the molecule. Only
# unambiguous words belong here — anything that could plausibly be part of a
# compound's name is left to the narrower number-paired rule below.
_MODIFIERS = {
    "buy", "shop", "order", "purchase", "get", "online", "store",
    "sale", "for", "best", "top", "cheap", "premium", "quality",
    "research", "grade", "pure", "usa", "us", "uk",
    "vial", "vials", "bottle", "bottles", "capsule", "capsules",
    "tablet", "tablets", "pack", "packs", "kit", "kits", "sachet",
    "sachets", "syringe", "syringes", "pen", "pens",
}

# Dosage / volume / count tokens. The invariant specs of a compound are the same
# across pack sizes, so these are noise for cache purposes.
#
# Two forms, handled differently on purpose:
#   - ATTACHED ("1200mg", "10ml", "60ct") — unambiguous, always dropped.
#   - BARE ("5 mg") — the unit is dropped ONLY when it directly follows a
#     number, because a bare unit symbol is often part of a compound's name.
#     "L-Carnitine" tokenizes to ["l", "carnitine"] and "l" is also the symbol
#     for litres; stripping it unconditionally merged L-Carnitine with plain
#     carnitine, which is a different molecule.
# A bare number is never dropped on its own — a number can BE the identity
# (BPC-157, TB-500).
_UNITS = r"mg|mcg|ug|g|kg|ml|l|iu|ct|count|caps?|tabs?"
_DOSE_RE = re.compile(rf"^\d+(?:\.\d+)?(?:{_UNITS})$")
_UNIT_ONLY_RE = re.compile(rf"^(?:{_UNITS})$")
_NUMBER_RE = re.compile(r"^\d+(?:\.\d+)?$")


def normalize_entity_key(keyword: Optional[str]) -> str:
    """Normalize a product keyword to a cache key for its underlying compound.

    Lowercases, drops punctuation (so hyphens do not split an identity —
    "BPC-157" and "BPC 157" agree), drops commercial modifiers, and drops
    dosage/volume tokens. Returns '' when nothing identifying survives, which
    the callers treat as "do not cache".

    Deliberately conservative. Over-normalizing is the dangerous direction: it
    would serve one compound's CAS number for a different product. "BPC-157" and
    "BPC-157 TB-500" (a blend) must stay distinct keys, and they do — only
    modifier and dosage tokens are removed, never a compound token.
    """
    text = re.sub(r"[^a-z0-9\s]+", " ", (keyword or "").lower())
    tokens = [t for t in text.split() if t]

    kept: list[str] = []
    for i, token in enumerate(tokens):
        if token in _MODIFIERS:
            continue
        if _DOSE_RE.match(token):
            continue
        if _UNIT_ONLY_RE.match(token) and kept and _NUMBER_RE.match(kept[-1]):
            # "5 mg" — drop the unit AND the number it belongs to. Only in that
            # pairing: a bare unit token is often part of the compound's name
            # ("L-Carnitine" tokenizes to ["l", "carnitine"], and "l" is also
            # the symbol for litres — stripping it unconditionally silently
            # merged L-Carnitine with plain carnitine).
            kept.pop()
            continue
        kept.append(token)

    # A key made only of numbers carries no compound identity ("1200 10").
    if not any(not _NUMBER_RE.match(t) for t in kept):
        return ""
    return " ".join(kept)


def is_fresh(fetched_at: Optional[str], ttl_days: int, now: Optional[datetime] = None) -> bool:
    """Whether a cached row is still within its TTL.

    An unparseable/missing timestamp counts as STALE — the safe direction is to
    re-research (costing one pass) rather than serve an entry of unknown age.
    `ttl_days <= 0` disables freshness entirely (every row reads as stale).
    """
    if ttl_days <= 0 or not fetched_at:
        return False
    now = now or datetime.now(timezone.utc)
    try:
        stamp = datetime.fromisoformat(str(fetched_at).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp > now - timedelta(days=ttl_days)


def cache_row(
    entity_key: str, entity: str, page_type: str, facts: list,
    source_page_id: Optional[str] = None,
) -> dict:
    """Build the upsert row for a cache fill (pure — unit-testable)."""
    return {
        "entity_key": entity_key,
        "entity": (entity or "").strip(),
        "page_type": page_type,
        "facts": facts,
        "source_page_id": source_page_id,
        "fetched_at": "now()",
        "updated_at": "now()",
    }


# ── Supabase round-trips (best-effort — a cache outage must never fail a page) ──

def get_cached_facts(keyword: str, page_type: str) -> Optional[list]:
    """Return cached researched facts for `keyword`, or None on any miss.

    None means "research it" — an expired entry, an empty entry, a disabled
    cache, a non-product page, or a Supabase error all read the same way, so the
    caller has exactly one code path for the miss.
    """
    if not settings.ecommerce_fact_cache_enabled or page_type != "product":
        return None
    entity_key = normalize_entity_key(keyword)
    if not entity_key:
        return None
    try:
        res = (
            get_supabase().table(_TABLE)
            .select("facts, fetched_at").eq("entity_key", entity_key).limit(1).execute()
        )
    except Exception:  # noqa: BLE001 — a cache read must never break generation
        logger.warning("ecommerce.facts_cache_read_failed", extra={"entity_key": entity_key})
        return None
    row = (res.data or [None])[0]
    if not row:
        return None
    facts = row.get("facts") or []
    if not facts or not is_fresh(row.get("fetched_at"), settings.ecommerce_fact_cache_days):
        return None
    logger.info(
        "ecommerce.facts_cache_hit",
        extra={"entity_key": entity_key, "keyword": keyword, "facts": len(facts)},
    )
    return facts


def store_facts(
    keyword: str, page_type: str, facts: Optional[list],
    source_page_id: Optional[str] = None,
) -> None:
    """Fill the cache from a completed run's researched facts. Best-effort.

    An EMPTY result is not stored: "we found nothing this time" is not the same
    as "there is nothing", and caching it would permanently gate a compound that
    a later pass would have found specs for.
    """
    if not settings.ecommerce_fact_cache_enabled or page_type != "product" or not facts:
        return
    entity_key = normalize_entity_key(keyword)
    if not entity_key:
        return
    try:
        get_supabase().table(_TABLE).upsert(
            cache_row(entity_key, keyword, page_type, facts, source_page_id),
            on_conflict="entity_key",
        ).execute()
        logger.info(
            "ecommerce.facts_cache_stored",
            extra={"entity_key": entity_key, "keyword": keyword, "facts": len(facts)},
        )
    except Exception:  # noqa: BLE001 — a cache write must never break generation
        logger.warning("ecommerce.facts_cache_write_failed", extra={"entity_key": entity_key})
