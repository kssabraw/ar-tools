"""AI Visibility — auxiliary OpenAI features: invisibility diagnosis and
keyword suggestions. Both are on-demand (not per-scan-row), so they use the
latest OpenAI flagship. Prompts ported from brand-strength-ai's
diagnose-invisibility / suggest-keywords edge functions.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Optional

from config import settings


# How far back to summarize Google Search Console performance for the keyword
# when grounding the diagnosis (matches the rank tracker's recent-window feel).
_GSC_WINDOW_DAYS = 28


class InsightUnavailable(Exception):
    """OpenAI isn't configured or the call failed irrecoverably."""


def _client():
    if not settings.openai_api_key:
        raise InsightUnavailable("openai_not_configured")
    import openai

    return openai.AsyncOpenAI(api_key=settings.openai_api_key)


def _diagnosis_prompt(brand: str, keyword: str, raw_response: str, signals_block: str = "") -> str:
    prompt = (
        f'The brand "{brand}" was searched for using the query "{keyword}" but was '
        f"NOT found in the results.\n\nHere are the businesses that WERE found:\n"
        f'"""\n{(raw_response or "")[:4000]}\n"""\n\n'
    )
    if signals_block:
        prompt += (
            "REAL DATA about this client and the competitive landscape for this "
            "query (from our own tracking — prefer these facts over assumptions and "
            "do NOT contradict them):\n"
            f"{signals_block}\n\n"
        )
    prompt += (
        f'Analyze why "{brand}" might be invisible to this AI search and provide:\n'
        "1. What types of businesses ARE appearing (and why they likely rank)\n"
    )
    if signals_block:
        prompt += (
            "2. Specific reasons this brand is missing — ground these in the REAL "
            "DATA above (e.g. its review count/rating vs. what this query rewards, "
            "category fit, the backlink/domain-authority gap vs. the competitors "
            "shown, and whether it ranks organically at all)\n"
        )
    else:
        prompt += (
            "2. Specific reasons this brand might be missing (weak SEO, no reviews, no listings, etc.)\n"
        )
    prompt += (
        "3. 2-3 actionable steps to improve AI visibility for this specific query\n\n"
        "Be specific and reference the actual competitors shown"
        f"{' and the real metrics provided' if signals_block else ''}. Keep the "
        "response concise (under 250 words). Format with clear sections."
    )
    return prompt


# ── real client signals (already-stored data, no live API calls) ──────────────

def gather_client_signals(client_id: str, keyword: str) -> dict:
    """Assemble real, already-captured client signals to ground the diagnosis:
    the client's GBP strength (rating/reviews/categories) and the competitive
    backlink authority + organic rank from the latest matching SERP snapshot.

    Reads only stored tables (clients.gbp, serp_snapshot_*) — no external API
    calls. Best-effort: each sub-source is isolated, so a missing GBP / no
    snapshot / a query error yields a partial (or empty) dict, never raises."""
    from db.supabase_client import get_supabase

    supabase = get_supabase()
    signals: dict = {}

    # GBP strength — the dominant local AI-visibility factor.
    try:
        rows = supabase.table("clients").select("gbp").eq("id", client_id).limit(1).execute().data
        gbp = (rows[0].get("gbp") if rows else None) or {}
        if gbp.get("gbp_rating") is not None or gbp.get("gbp_review_count") is not None or gbp.get("gbp_category"):
            signals["gbp"] = {
                "rating": gbp.get("gbp_rating"),
                "review_count": gbp.get("gbp_review_count"),
                "primary_category": gbp.get("gbp_category") or "",
                "categories": [c for c in (gbp.get("gbp_categories") or []) if c][:6],
                "has_website": bool(gbp.get("website")),
                "has_description": bool(gbp.get("description")),
            }
    except Exception:  # pragma: no cover - best-effort
        pass

    # Competitive authority + the client's own organic rank, from the latest
    # SERP snapshot whose keyword matches this query (case-insensitive exact).
    try:
        snaps = (
            supabase.table("serp_snapshots")
            .select("id, captured_at, client_rank, status")
            .eq("client_id", client_id)
            .ilike("keyword", keyword)
            .neq("status", "failed")
            .order("captured_at", desc=True)
            .limit(1)
            .execute()
            .data
        ) or []
        if snaps:
            snap = snaps[0]
            domains = (
                supabase.table("serp_snapshot_domains")
                .select("domain, is_client, domain_rating, referring_domains")
                .eq("snapshot_id", snap["id"])
                .execute()
                .data
            ) or []
            client_dom = next((d for d in domains if d.get("is_client")), None)
            competitors = sorted(
                (d for d in domains if not d.get("is_client") and d.get("domain_rating") is not None),
                key=lambda d: d["domain_rating"],
                reverse=True,
            )[:5]
            signals["serp"] = {
                "captured_at": snap.get("captured_at"),
                "client_rank": snap.get("client_rank"),
                "client_domain_rating": (client_dom or {}).get("domain_rating"),
                "competitors": [
                    {"domain": d.get("domain"), "dr": d.get("domain_rating"),
                     "referring_domains": d.get("referring_domains")}
                    for d in competitors
                ],
            }
    except Exception:  # pragma: no cover - best-effort
        pass

    # Classic Google Search performance for this exact query (GSC), if the client
    # has a verified property. Grounds the AI-answer gap against how the client
    # actually performs in organic search (e.g. ranks well in Search but is
    # invisible in AI answers — a very different problem than ranking nowhere).
    try:
        prop = (
            supabase.table("gsc_properties")
            .select("id")
            .eq("client_id", client_id)
            .eq("access_status", "ok")
            .order("created_at")
            .limit(1)
            .execute()
            .data
        )
        if prop:
            from datetime import date, timedelta

            since = (date.today() - timedelta(days=_GSC_WINDOW_DAYS)).isoformat()
            rows = (
                supabase.table("gsc_query_daily")
                .select("clicks, impressions, position")
                .eq("property_id", prop[0]["id"])
                .ilike("query", keyword)
                .gte("date", since)
                .execute()
                .data
            ) or []
            if rows:
                clicks = sum(int(r.get("clicks") or 0) for r in rows)
                impressions = sum(int(r.get("impressions") or 0) for r in rows)
                weighted = [
                    (float(r["position"]), int(r.get("impressions") or 0))
                    for r in rows if r.get("position") is not None
                ]
                avg_pos = None
                tot_imp = sum(i for _, i in weighted)
                if weighted and tot_imp > 0:
                    avg_pos = round(sum(p * i for p, i in weighted) / tot_imp, 1)
                elif weighted:
                    avg_pos = round(sum(p for p, _ in weighted) / len(weighted), 1)
                signals["gsc"] = {
                    "window_days": _GSC_WINDOW_DAYS,
                    "clicks": clicks,
                    "impressions": impressions,
                    "avg_position": avg_pos,
                }
    except Exception:  # pragma: no cover - best-effort
        pass

    return signals


def format_signals_block(signals: dict) -> str:
    """Render gather_client_signals() output into a compact prompt block. Pure
    (no DB) so it's unit-testable. Returns "" when there's nothing to show."""
    lines: list[str] = []

    gbp = signals.get("gbp")
    if gbp:
        bits = []
        if gbp.get("rating") is not None and gbp.get("review_count") is not None:
            bits.append(f"{gbp['rating']}★ from {gbp['review_count']} reviews")
        elif gbp.get("review_count") is not None:
            bits.append(f"{gbp['review_count']} reviews")
        if gbp.get("primary_category"):
            bits.append(f'primary category "{gbp["primary_category"]}"')
        cats = [c for c in (gbp.get("categories") or []) if c and c != gbp.get("primary_category")]
        if cats:
            bits.append("also categorized as " + ", ".join(cats))
        completeness = []
        if not gbp.get("has_website"):
            completeness.append("no website on the profile")
        if not gbp.get("has_description"):
            completeness.append("no description on the profile")
        if completeness:
            bits.append("; ".join(completeness))
        if bits:
            lines.append("- Google Business Profile: " + "; ".join(bits) + ".")

    serp = signals.get("serp")
    if serp:
        rank = serp.get("client_rank")
        rank_txt = (
            f"the client's site ranks #{rank} organically"
            if rank else "the client's site does NOT rank in the captured top results"
        )
        client_dr = serp.get("client_domain_rating")
        dr_txt = f" (its domain rating is {client_dr})" if client_dr is not None else ""
        comp = serp.get("competitors") or []
        if comp:
            comp_txt = ", ".join(
                f"{c['domain']} DR {c['dr']}"
                + (f"/{c['referring_domains']} ref. domains" if c.get("referring_domains") is not None else "")
                for c in comp if c.get("domain")
            )
            comp_line = f" Competitors ranking for this query: {comp_txt}."
        else:
            comp_line = ""
        lines.append(
            f"- Organic SERP for this exact query: {rank_txt}{dr_txt}.{comp_line}"
        )

    gsc = signals.get("gsc")
    if gsc:
        bits = [f"{gsc['impressions']:,} impressions", f"{gsc['clicks']:,} clicks"]
        pos = gsc.get("avg_position")
        if pos is not None:
            bits.append(f"average position {pos}")
        lines.append(
            f"- Google Search performance (last {gsc['window_days']} days, this exact query): "
            + ", ".join(bits) + "."
        )

    fb = signals.get("search_fallback")
    if fb:
        bits = []
        rank = fb.get("rank")
        bits.append(
            f"the client's site ranks #{rank} organically"
            if rank else "the client's site does NOT rank in the top organic results"
        )
        vol = fb.get("search_volume")
        if vol is not None:
            comp = fb.get("competition")
            comp_txt = f", {str(comp).lower()} competition" if comp else ""
            bits.append(f"the keyword gets ~{vol:,} searches/mo{comp_txt}")
        lines.append(
            "- Classic Google Search (live DataForSEO check — no GSC connected): "
            + "; ".join(bits) + "."
        )

    return "\n".join(lines)


# ── live DataForSEO fallback for the GSC layer ────────────────────────────────
# A keyword invisible across all engines triggers gather/diagnose once per cell,
# so a naive live SERP call per cell would multiply by the engine count. Memoize
# the (paid) lookup per (client, keyword, location) for a short TTL so those
# concurrent cells share one call.
_FALLBACK_TTL = 600.0
_fallback_cache: dict[tuple, Optional[dict]] = {}
_fallback_expiry: dict[tuple, float] = {}
_fallback_locks: dict[tuple, "asyncio.Lock"] = {}


async def _compute_search_fallback(supabase, keyword: str, domain: str, location_code: int) -> Optional[dict]:
    """One live DataForSEO lookup: the client's organic rank + the keyword's
    search volume (cached cross-client first, else one live call)."""
    from services import dataforseo_rank, keyword_market

    rank = None
    if domain:
        try:
            rank = await dataforseo_rank.fetch_serp_rank(keyword, domain, location_code)
        except Exception:  # pragma: no cover - provider hiccup
            rank = None

    row = None
    try:
        cached = keyword_market.fetch_cached_market(supabase, [keyword], location_code)
        row = cached.get(keyword.lower())
        if not row:
            live = await keyword_market.fetch_market([keyword], location_code)
            row = live.get(keyword.lower())
    except Exception:  # pragma: no cover - provider hiccup
        row = None

    volume = (row or {}).get("search_volume")
    if rank is None and volume is None:
        return None
    return {
        "source": "dataforseo",
        "rank": rank,
        "search_volume": volume,
        "competition": (row or {}).get("competition"),
    }


async def fetch_search_fallback(client_id: str, keyword: str) -> Optional[dict]:
    """Live DataForSEO stand-in for the GSC layer when GSC isn't available: the
    client's organic position for the keyword + the keyword's search volume.
    Best-effort (returns None when DataForSEO isn't configured or the lookup
    fails) and memoized per (client, keyword, location) so a keyword invisible
    across engines costs a single paid lookup."""
    if not settings.dataforseo_login or not settings.dataforseo_password:
        return None
    from db.supabase_client import get_supabase
    from services import dataforseo_rank

    supabase = get_supabase()
    try:
        rows = (
            supabase.table("clients")
            .select("website_url, gbp, rank_tracking_location_code")
            .eq("id", client_id).limit(1).execute().data
        )
    except Exception:  # pragma: no cover - best-effort
        return None
    if not rows:
        return None
    client = rows[0]
    domain = dataforseo_rank.extract_domain(
        client.get("website_url") or (client.get("gbp") or {}).get("website") or ""
    )
    location_code = dataforseo_rank.location_code_for(client)
    key = (client_id, keyword.lower(), location_code)

    now = time.monotonic()
    if key in _fallback_cache and _fallback_expiry.get(key, 0) > now:
        return _fallback_cache[key]
    lock = _fallback_locks.setdefault(key, asyncio.Lock())
    async with lock:
        now = time.monotonic()
        if key in _fallback_cache and _fallback_expiry.get(key, 0) > now:
            return _fallback_cache[key]
        value = await _compute_search_fallback(supabase, keyword, domain, location_code)
        _fallback_cache[key] = value
        _fallback_expiry[key] = time.monotonic() + _FALLBACK_TTL
        return value


async def build_signals_block(client_id: str, keyword: str) -> str:
    """Single entry point used by both diagnosis paths: gather the stored signals
    (GBP + SERP snapshot + GSC) and, only when neither GSC nor a SERP snapshot
    covers the keyword, fall back to a live DataForSEO rank/volume lookup. Returns
    the formatted prompt block ("" when nothing is available). Never raises."""
    signals = gather_client_signals(client_id, keyword)
    if not signals.get("gsc") and not signals.get("serp"):
        fb = await fetch_search_fallback(client_id, keyword)
        if fb:
            signals["search_fallback"] = fb
    return format_signals_block(signals)


async def diagnose_invisibility(
    brand: str, keyword: str, raw_response: str, signals_block: str = ""
) -> str:
    client = _client()
    try:
        resp = await client.chat.completions.create(
            model=settings.brand_diagnose_model,
            messages=[
                {"role": "system", "content": "You are a local SEO and AI Answer Engine Optimization expert."},
                {"role": "user", "content": _diagnosis_prompt(brand, keyword, raw_response, signals_block)},
            ],
        )
    except Exception as exc:  # pragma: no cover - thin provider wrapper
        raise InsightUnavailable(str(exc))
    return (resp.choices[0].message.content or "").strip()


def _suggest_prompt(
    brand: str,
    business_types: list[str],
    address: Optional[str],
    *,
    local: bool = True,
    business_context: str = "",
) -> str:
    type_ctx = f"Business types: {', '.join(business_types)}." if business_types else ""
    loc_ctx = f"Located at: {address}." if address else ""
    ctx_ctx = f"About the business: {business_context.strip()}" if business_context.strip() else ""
    if local:
        return (
            "You are an expert at local SEO and AI Answer Engine Optimization. Generate "
            "exactly 5 high-intent search keywords that potential customers would use to "
            "find this business through AI assistants like ChatGPT, Gemini, or Perplexity.\n\n"
            f"Business name: {brand}\n{type_ctx}\n{loc_ctx}\n{ctx_ctx}\n\n"
            "Requirements:\n"
            '- Focus on local/service-intent keywords (e.g., "emergency plumber Sydney", "24 hour AC repair")\n'
            '- Never use the phrase "near me"; use the actual suburb/city for local intent\n'
            f'- Include the business name in at least one keyword (e.g., "{brand} reviews")\n'
            "- Make keywords specific to the business type, not generic\n"
            "- Keywords should be what someone would ask an AI assistant\n"
            "- Return ONLY a JSON array of 5 strings, nothing else"
        )
    # Non-local / website-only client: a business that doesn't compete on a
    # geographic footprint (SaaS, e-commerce, national/online service). Ground
    # on what it offers (from the website-derived context) rather than a place.
    return (
        "You are an expert at AI Answer Engine Optimization (AEO). Generate exactly 5 "
        "high-intent search queries that potential customers would use to find this "
        "business through AI assistants like ChatGPT, Gemini, or Perplexity.\n\n"
        f"Business name: {brand}\n{type_ctx}\n{ctx_ctx}\n\n"
        "Requirements:\n"
        "- Focus on the customer's need and the product/service category this business "
        "offers — NOT a location (this is not a local business, so do not append a "
        "city/suburb or use the phrase \"near me\")\n"
        f'- Include the business name in at least one keyword (e.g., "{brand} reviews", "{brand} alternatives")\n'
        "- Make keywords specific to what this business actually offers, not generic\n"
        "- Keywords should be what someone would ask an AI assistant\n"
        "- Return ONLY a JSON array of 5 strings, nothing else"
    )


def _parse_string_list(text: str, cap: int) -> list[str]:
    """Pull a JSON array of strings out of the model's reply, tolerating fences,
    trim/drop blanks, and cap the length."""
    if not text:
        return []
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    return [str(k).strip() for k in data if isinstance(k, (str, int)) and str(k).strip()][:cap]


def _parse_keyword_list(text: str) -> list[str]:
    """Pull a JSON array of up to 5 keyword strings out of the model's reply."""
    return _parse_string_list(text, cap=5)


# LABS keyword/query suggestions must never contain the phrase "near me" (owner
# preference, 2026-07): AI assistants already resolve "near me" to the asker's
# location, so it's noise as a tracked query — the actual suburb/city is what we
# want. Belt-and-suspenders: the suggestion prompts ask the model to avoid it,
# and this filter guarantees it regardless of what the model returns. Matches
# "near me", "near-me", "nearme" (any spacing/casing) as a whole phrase.
_NEAR_ME_RE = re.compile(r"\bnear[\s\-]*me\b", re.I)


def _drop_near_me(items: list[str]) -> list[str]:
    """Drop any suggestion containing the phrase "near me" (see _NEAR_ME_RE)."""
    return [s for s in items if not _NEAR_ME_RE.search(s)]


async def suggest_keywords(
    brand: str,
    business_types: list[str],
    address: Optional[str],
    *,
    local: bool = True,
    business_context: str = "",
) -> list[str]:
    client = _client()
    system = (
        "You are a local SEO expert. Return only valid JSON arrays."
        if local
        else "You are an AI Answer Engine Optimization (AEO) expert. Return only valid JSON arrays."
    )
    try:
        resp = await client.chat.completions.create(
            model=settings.brand_suggest_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": _suggest_prompt(
                    brand, business_types, address, local=local, business_context=business_context,
                )},
            ],
        )
    except Exception as exc:  # pragma: no cover
        raise InsightUnavailable(str(exc))
    return _drop_near_me(_parse_keyword_list(resp.choices[0].message.content or ""))


# ── conversational-query suggestions from tracked keywords ────────────────────
# Per-seed-keyword count of natural-language AI queries to generate.
_QUERIES_PER_KEYWORD_MIN = 3
_QUERIES_PER_KEYWORD_MAX = 5


def _conversational_prompt(
    brand: str, business_context: str, icp_text: str, seed_keywords: list[str],
    *, local: bool = True,
) -> str:
    """Prompt to expand each tracked ranking keyword into 3-5 conversational,
    ICP-grounded queries someone would actually type/ask an AI assistant. When
    ``local`` is False (a non-local / website-only client), the location-preserving
    and "near me" framing is dropped so suggestions stay category/need-focused."""
    ctx = business_context.strip() or brand or ("this local business" if local else "this business")
    icp_block = (
        "The ideal customer (ICP) for this business:\n" + icp_text.strip() + "\n\n"
        if icp_text.strip()
        else "No explicit ICP is on file — infer the realistic ideal customer from the "
        "business context above.\n\n"
    )
    seeds = "\n".join(f"- {k}" for k in seed_keywords)
    expert = (
        "AI Answer Engine Optimization (AEO) and local SEO" if local
        else "AI Answer Engine Optimization (AEO)"
    )
    example = (
        'who\'s the best emergency plumber in Sydney for a burst pipe?' if local
        else 'what\'s the best tool for scheduling social media posts for a small team?'
    )
    if local:
        location_reqs = (
            "- Preserve the seed keyword's location and qualifier (an emergency/suburb "
            "term stays that specific).\n"
            '- Never use the phrase "near me". If a seed keyword says "near me", resolve '
            "it to the business's actual city/suburb (from the business context above) "
            "instead — a real person talking to an AI names the place.\n"
        )
    else:
        location_reqs = (
            "- This is not a local business — do NOT append a city/suburb or use the "
            'phrase "near me". Keep queries focused on the need, category, and how this '
            "business is chosen (features, alternatives, use case, pricing intent).\n"
        )
    return (
        f"You are an expert in {expert}. "
        "The business below is tracked for a set of ranking keywords. For EACH seed "
        "keyword, write natural-language, conversational queries that its ideal "
        "customer would actually ask an AI assistant (ChatGPT, Gemini, Perplexity, "
        "Google AI Overviews) when they have the need behind that keyword.\n\n"
        f"Business: {ctx}\n\n"
        f"{icp_block}"
        "Seed keywords (from the organic + geo-grid rank trackers):\n"
        f"{seeds}\n\n"
        "Requirements:\n"
        f"- Produce {_QUERIES_PER_KEYWORD_MIN}-{_QUERIES_PER_KEYWORD_MAX} conversational "
        "queries per seed keyword.\n"
        "- Write full natural questions/requests, the way a real person talks to an AI "
        f'(e.g. "{example}"), '
        "NOT keyword fragments.\n"
        "- Keep each query SHORT and natural: one sentence, roughly 8-14 words, the way "
        "someone actually types into an AI. Do not exceed ~16 words.\n"
        "- One thought per query: a single need or situation. Do NOT stack multiple "
        "clauses/qualifiers into one question (no run-ons chaining time + price + "
        "guarantee + availability). If a seed keyword implies several angles, split them "
        "across separate queries rather than cramming them into one.\n"
        "- Ground each query in the ideal customer's real situation and intent from the "
        "ICP above, but reflect it through ONE concrete angle per query — do not narrate "
        "the whole customer profile in a single question.\n"
        f"{location_reqs}"
        "- Keep them commercial/high-intent (finding or choosing a provider), not "
        "generic informational trivia.\n"
        "- Return ONLY a flat JSON array of all the query strings, nothing else."
    )


async def suggest_conversational_queries(
    brand: str, business_context: str, icp_text: str, seed_keywords: list[str],
    *, local: bool = True,
) -> list[str]:
    """Expand tracked ranking keywords into ICP-grounded conversational AI queries.
    One flagship call; returns a flat, de-duplicated list (case-insensitive)."""
    if not seed_keywords:
        return []
    client = _client()
    system = (
        "You are an AEO/local SEO expert. Return only valid JSON arrays." if local
        else "You are an AEO expert. Return only valid JSON arrays."
    )
    try:
        resp = await client.chat.completions.create(
            model=settings.brand_suggest_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": _conversational_prompt(
                    brand, business_context, icp_text, seed_keywords, local=local,
                )},
            ],
        )
    except Exception as exc:  # pragma: no cover
        raise InsightUnavailable(str(exc))
    cap = len(seed_keywords) * _QUERIES_PER_KEYWORD_MAX
    parsed = _drop_near_me(_parse_string_list(resp.choices[0].message.content or "", cap=cap))
    seen: set[str] = set()
    out: list[str] = []
    for q in parsed:
        key = q.lower()
        if key not in seen:
            seen.add(key)
            out.append(q)
    return out
