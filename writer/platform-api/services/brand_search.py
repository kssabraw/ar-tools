"""Brand-search analysis — branded vs non-branded Google Search Console demand
over time, a brand-health signal for the Action Plan and the rank tracker.

Reads the GSC query×date history we already ingest (`gsc_query_daily`); no new
fetch. A query is "branded" when it contains the business name (as a phrase) or
one of its distinctive name tokens. Brand terms are derived from the client name
+ GBP business name (generic/legal/service words stripped); a manual override
column is a deliberate follow-up.

Pure helpers (unit-tested); the router resolves the client's property + brand
terms and the reoptimization planner reuses `detect_brand_decline`.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

# Words too generic to identify a brand on their own (legal suffixes + the most
# common trade/service words). Kept small and conservative — distinctive tokens
# like "ace" or "redback" survive and drive branded classification.
_GENERIC = {
    "the", "and", "of", "for", "co", "inc", "llc", "ltd", "pty", "group", "company",
    "services", "service", "solutions", "and", "your", "local",
    "plumbing", "plumber", "plumbers", "roofing", "roofer", "roofers", "electrical",
    "electrician", "electricians", "hvac", "heating", "cooling", "air", "dental",
    "dentist", "law", "lawyers", "legal", "clinic", "medical", "construction",
    "builders", "building", "landscaping", "cleaning", "pest", "control",
}


def derive_brand_terms(name: "str | None", gbp_business_name: "str | None" = None) -> list[str]:
    """Brand terms from the business name(s): the full name as a phrase plus its
    distinctive (non-generic) tokens, all lowercased. Pure."""
    terms: set[str] = set()
    for raw in (name, gbp_business_name):
        if not raw:
            continue
        n = raw.strip().lower()
        if not n:
            continue
        terms.add(n)  # full name as a phrase
        for tok in re.findall(r"[a-z0-9]+", n):
            if len(tok) >= 3 and tok not in _GENERIC:
                terms.add(tok)
    return sorted(terms)


def resolve_brand_terms(client: dict) -> list[str]:
    """A client's brand terms — the manual override if present, else derived from
    the client name + stored GBP business name."""
    manual = client.get("brand_terms")
    if manual:
        return [t.strip().lower() for t in manual if t and t.strip()]
    gbp = client.get("gbp") if isinstance(client.get("gbp"), dict) else {}
    return derive_brand_terms(client.get("name"), (gbp or {}).get("business_name"))


def classify_query(query: "str | None", terms: list[str]) -> bool:
    """True when the query is branded: it contains a multi-word brand phrase, or
    one of the single-token brand terms as a whole word. Pure."""
    if not query or not terms:
        return False
    q = query.lower()
    qwords = set(re.findall(r"[a-z0-9]+", q))
    for t in terms:
        if " " in t:
            if t in q:
                return True
        elif t in qwords:
            return True
    return False


def _week_start(d: str) -> "str | None":
    try:
        dt = date.fromisoformat(d)
    except (ValueError, TypeError):
        return None
    return (dt - timedelta(days=dt.weekday())).isoformat()  # Monday of that week


def build_brand_search(rows: list[dict], terms: list[str]) -> dict:
    """Bucket GSC query×date rows into a weekly branded-vs-non-branded series.
    Returns {series:[{week, branded_impressions, nonbranded_impressions,
    branded_clicks, nonbranded_clicks, branded_share_pct}], totals:{...},
    brand_terms}. Pure (DB-free)."""
    weeks: dict[str, dict] = {}
    t_bi = t_ni = t_bc = t_nc = 0
    for r in rows:
        wk = _week_start(r.get("date"))
        if wk is None:
            continue
        impr = int(r.get("impressions") or 0)
        clk = int(r.get("clicks") or 0)
        w = weeks.setdefault(
            wk,
            {"week": wk, "branded_impressions": 0, "nonbranded_impressions": 0,
             "branded_clicks": 0, "nonbranded_clicks": 0},
        )
        if classify_query(r.get("query"), terms):
            w["branded_impressions"] += impr
            w["branded_clicks"] += clk
            t_bi += impr
            t_bc += clk
        else:
            w["nonbranded_impressions"] += impr
            w["nonbranded_clicks"] += clk
            t_ni += impr
            t_nc += clk
    series = []
    for w in sorted(weeks.values(), key=lambda x: x["week"]):
        tot = w["branded_impressions"] + w["nonbranded_impressions"]
        w["branded_share_pct"] = round(w["branded_impressions"] / tot * 100, 1) if tot else None
        series.append(w)
    total_impr = t_bi + t_ni
    totals = {
        "branded_impressions": t_bi,
        "nonbranded_impressions": t_ni,
        "branded_clicks": t_bc,
        "nonbranded_clicks": t_nc,
        "branded_share_pct": round(t_bi / total_impr * 100, 1) if total_impr else None,
    }
    return {"series": series, "totals": totals, "brand_terms": terms}


def _page_query_daily(supabase, property_id: str, start: str) -> list[dict]:
    """Page through gsc_query_daily (query×date) from `start` — a busy property
    can exceed PostgREST's default 1000-row cap, so we range until exhausted."""
    out: list[dict] = []
    size = 1000
    for page in range(0, 200):  # safety bound (200k rows)
        res = (
            supabase.table("gsc_query_daily")
            .select("query, date, clicks, impressions")
            .eq("property_id", property_id)
            .gte("date", start)
            .range(page * size, page * size + size - 1)
            .execute()
        )
        batch = res.data or []
        out.extend(batch)
        if len(batch) < size:
            break
    return out


def load_brand_series(supabase, client_id: str, days: int = 90) -> dict:
    """Impure orchestration: resolve the client's brand terms + verified GSC
    property, page through gsc_query_daily, and return build_brand_search(...)
    plus `gsc_connected`. Returns an empty (but well-formed) payload when the
    client has no verified property."""
    from datetime import date, timedelta

    from services import rank_materialize

    rows = supabase.table("clients").select("name, gbp").eq("id", client_id).limit(1).execute().data
    client = rows[0] if rows else {}
    terms = resolve_brand_terms(client)
    property_id = rank_materialize._verified_property_id(supabase, client_id)
    if not property_id:
        out = build_brand_search([], terms)
        out["gsc_connected"] = False
        return out
    start = (date.today() - timedelta(days=days)).isoformat()
    out = build_brand_search(_page_query_daily(supabase, property_id, start), terms)
    out["gsc_connected"] = True
    return out


def detect_brand_decline(series: list[dict], min_drop_pct: float, window: int = 4) -> "dict | None":
    """Compare branded impressions in the most recent `window` weeks vs the prior
    `window` weeks; return a decline signal when they fell by >= min_drop_pct
    (relative %), else None. Pure — feeds the Action Plan."""
    if len(series) < window * 2:
        return None
    recent = series[-window:]
    prior = series[-window * 2:-window]
    recent_sum = sum(w["branded_impressions"] for w in recent)
    prior_sum = sum(w["branded_impressions"] for w in prior)
    if prior_sum <= 0:
        return None
    delta_pct = round((prior_sum - recent_sum) / prior_sum * 100, 1)  # positive = decline
    if delta_pct < min_drop_pct:
        return None
    return {
        "from_impressions": prior_sum,
        "to_impressions": recent_sum,
        "delta_pct": delta_pct,
        "weeks": window,
    }
