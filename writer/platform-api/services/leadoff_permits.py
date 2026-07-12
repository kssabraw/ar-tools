"""Census building-permits "prospect pipeline" — app-side (the whole flow
runs on the deployed worker; no desktop scanner involvement, no API key).

Spec: docs/modules/leadoff-permits-plan-v1_0.md (app-side revision). New
housing permits are a LEADING indicator of home-services demand (permits →
construction → move-ins → HVAC/roofing/plumbing work 6–18 months later).
**Context column only** — never a build_score/grade input (permits are
lagged + category-specific; any future weight must be earned through the
calibration framework, leadoff-calibration-plan §5).

Source: BPS annual place files — keyless, $0 —
https://www2.census.gov/econ/bps/Place/<Region>/<region><yyyy>a.txt
(two header rows to combine; column names drift across vintages — the
parser matches by keyword and FAILS LOUDLY rather than guessing; the
"imputed estimate" Units columns are the published numbers, the
"reported-only" section is excluded by the `rep` forbid).

Storage: public.city_permits keyed by the scanner's city_id — app-owned
deliberately (leadoff_board is drop/recreated by the scanner loader, so
columns written there would be wiped). Board/brief reads join at request
time (services/leadoff.attach_permits).

Validation (working agreement): every run's job result carries the
McKinney TX (Sun-Belt boomtown) vs Cleveland OH (stable Rust-Belt)
side-by-side — if those two ever look interchangeable, distrust the column.
"""
from __future__ import annotations

import csv
import io
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

BASE = "https://www2.census.gov/econ/bps/Place"
REGIONS = {"ne": "Northeast", "mw": "Midwest", "so": "South", "we": "West"}
STATE_REGION = {
    **{s: "ne" for s in "CT ME MA NH RI VT NJ NY PA".split()},
    **{s: "mw" for s in "IL IN MI OH WI IA KS MN MO NE ND SD".split()},
    **{s: "so" for s in "DE FL GA MD NC SC VA WV DC AL KY MS TN AR LA OK TX".split()},
    **{s: "we" for s in "AZ CO ID MT NV NM UT WY AK CA HI OR WA".split()},
}
STATE_FIPS = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08", "CT": "09",
    "DE": "10", "DC": "11", "FL": "12", "GA": "13", "HI": "15", "ID": "16", "IL": "17",
    "IN": "18", "IA": "19", "KS": "20", "KY": "21", "LA": "22", "ME": "23", "MD": "24",
    "MA": "25", "MI": "26", "MN": "27", "MS": "28", "MO": "29", "MT": "30", "NE": "31",
    "NV": "32", "NH": "33", "NJ": "34", "NM": "35", "NY": "36", "NC": "37", "ND": "38",
    "OH": "39", "OK": "40", "OR": "41", "PA": "42", "RI": "44", "SC": "45", "SD": "46",
    "TN": "47", "TX": "48", "UT": "49", "VT": "50", "VA": "51", "WA": "53", "WV": "54",
    "WI": "55", "WY": "56",
}
VALIDATE_MARKETS = [("McKinney", "TX"), ("Cleveland", "OH")]
TREND_BASE_YEARS = 3
HOT_TREND, COLD_TREND = 1.2, 0.8
FLAG_HI_Q, FLAG_LO_Q = 0.9, 0.1

# Categories where new-construction volume plausibly leads demand — drives
# DISPLAY prominence only (plan §4: relevance is display, never a weight).
_CONSTRUCTION_ADJACENT = (
    "hvac", "heating", "air conditioning", "plumb", "roof", "landscap",
    "electric", "fence", "fencing", "concrete", "garage door", "painter",
    "painting", "floor", "insulation", "septic", "paving", "deck", "gutter",
    "siding", "tree service", "arborist", "irrigation", "excavat", "masonry",
    "carpenter", "drywall", "tile", "countertop", "cabinet", "pool",
)


# ── Pure helpers (unit-tested in tests/test_leadoff_permits.py) ───────────────

def norm_place(s: str) -> str:
    """BPS place names carry type suffixes ('McKinney city') — normalize and
    strip them so they match the scanner's city names."""
    n = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", str(s).lower())).strip()
    return re.sub(r"\s+(city|town|village|borough|township|cdp)$", "", n).strip()


def combine_headers(l1: str, l2: str) -> list[str]:
    h1, h2 = l1.split(","), l2.split(",")
    if len(h2) < len(h1):
        h2 += [""] * (len(h1) - len(h2))
    return [f"{a.strip()} {b.strip()}".strip() for a, b in zip(h1, h2)]


def find_col(cols: list[str], *kws: str, forbid: tuple[str, ...] = ()) -> int:
    """Index of the first column whose name carries every keyword and none of
    the forbidden ones. Raises (loudly) on layout drift."""
    for i, c in enumerate(cols):
        lc = c.lower()
        if all(k in lc for k in kws) and not any(f in lc for f in forbid):
            return i
    raise ValueError(f"bps_layout_drift: no column matching {kws} "
                     f"in {cols[:18]}…")


def parse_bps(text: str) -> dict[str, dict[str, float]]:
    """{state_fips|norm_place: {units_total, u1}} from one BPS annual file
    (two header rows, then CSV). Uses the imputed-estimate Units columns
    (forbids the 'rep'orted-only section). Duplicate places keep max."""
    lines = text.splitlines()
    if len(lines) < 3:
        raise ValueError("bps_file_too_short")
    cols = combine_headers(lines[0], lines[1])
    i_state = find_col(cols, "state", "code")
    i_name = find_col(cols, "place", "name")
    i_u1 = find_col(cols, "1-unit", "units", forbid=("rep",))
    i_u2 = find_col(cols, "2-unit", "units", forbid=("rep",))
    i_u34 = find_col(cols, "3-4", "units", forbid=("rep",))
    i_u5 = find_col(cols, "5", "units", forbid=("rep", "3-4"))
    out: dict[str, dict[str, float]] = {}
    for row in csv.reader(io.StringIO("\n".join(lines[2:]))):
        if len(row) <= max(i_state, i_name, i_u1, i_u2, i_u34, i_u5):
            continue
        def num(i: int) -> float:
            try:
                return float(row[i])
            except (ValueError, TypeError):
                return 0.0
        key = f"{row[i_state].strip().zfill(2)}|{norm_place(row[i_name])}"
        units = num(i_u1) + num(i_u2) + num(i_u34) + num(i_u5)
        prev = out.get(key)
        if prev is None or units > prev["units_total"]:
            out[key] = {"units_total": units, "u1": num(i_u1)}
    return out


def compute_metrics(population: Optional[float], latest_units: float,
                    latest_u1: float,
                    prior_units: list[float]) -> dict[str, Any]:
    """The plan §3 metrics from one city's yearly series. Pure."""
    pc = round(latest_units / population * 1000, 2) if population else None
    sf = round(latest_u1 / latest_units, 2) if latest_units else None
    base = sum(prior_units) / len(prior_units) if prior_units else None
    trend = round(latest_units / base, 2) if base else None
    return {"permit_units_1yr": round(latest_units), "permits_pc": pc,
            "permit_sf_share": sf, "permit_trend": trend}


def assign_flags(rows: list[dict[str, Any]]) -> None:
    """HOT/COLD-pipeline at p90/p10 permits_pc + trend bars (in place).
    Needs a real distribution — skipped under 10 covered cities."""
    vals = sorted(r["permits_pc"] for r in rows
                  if r.get("permits_pc") is not None)
    for r in rows:
        r.setdefault("permit_flag", "-")
    if len(vals) < 10:
        return
    p90 = vals[min(int(len(vals) * FLAG_HI_Q), len(vals) - 1)]
    p10 = vals[int(len(vals) * FLAG_LO_Q)]
    for r in rows:
        pc, tr = r.get("permits_pc"), r.get("permit_trend")
        if pc is None:
            continue
        if pc >= p90 and (tr or 0) >= HOT_TREND:
            r["permit_flag"] = "HOT-pipeline"
        elif pc <= p10 and tr is not None and tr <= COLD_TREND:
            r["permit_flag"] = "COLD-pipeline"


def permit_relevance(category: str) -> str:
    """'high' for construction-adjacent categories, else 'low' — display
    prominence only, never a numeric weight (plan §4)."""
    c = (category or "").lower()
    return "high" if any(k in c for k in _CONSTRUCTION_ADJACENT) else "low"


# ── Fetch + job ───────────────────────────────────────────────────────────────

async def _fetch_year(client: httpx.AsyncClient, year: int,
                      regions: set[str]) -> dict[str, dict[str, float]]:
    merged: dict[str, dict[str, float]] = {}
    for reg in sorted(regions):
        url = f"{BASE}/{REGIONS[reg]}/{reg}{year}a.txt"
        resp = await client.get(url, timeout=120.0)
        resp.raise_for_status()
        for k, v in parse_bps(resp.text).items():
            prev = merged.get(k)
            if prev is None or v["units_total"] > prev["units_total"]:
                merged[k] = v
    return merged


async def _latest_vintage(client: httpx.AsyncClient) -> int:
    year = datetime.now(timezone.utc).year
    for y in range(year, year - 4, -1):
        try:
            resp = await client.head(f"{BASE}/{REGIONS['we']}/we{y}a.txt",
                                     timeout=30.0)
            if resp.status_code == 200:
                return y
        except httpx.HTTPError:
            continue
    raise RuntimeError("bps_no_recent_vintage")


def _cities() -> list[dict[str, Any]]:
    from services.leadoff_db import get_leadoff_client
    return (get_leadoff_client().table("cities")
            .select("city_id, name, state_code, population")
            .execute().data or [])


async def run_permits_job(job: dict) -> None:
    supabase = get_supabase()
    job_id = job["id"]
    try:
        cities = _cities()
        regions = {STATE_REGION[c["state_code"]] for c in cities
                   if c.get("state_code") in STATE_REGION}
        async with httpx.AsyncClient(follow_redirects=True) as client:
            vintage = await _latest_vintage(client)
            latest = await _fetch_year(client, vintage, regions)
            priors = [await _fetch_year(client, vintage - i, regions)
                      for i in range(1, TREND_BASE_YEARS + 1)]

        now = datetime.now(timezone.utc).isoformat()
        rows: list[dict[str, Any]] = []
        for c in cities:
            fips = STATE_FIPS.get(c.get("state_code") or "")
            if not fips:
                continue
            key = f"{fips}|{norm_place(c.get('name') or '')}"
            base = {"city_id": c["city_id"], "city_name": c.get("name"),
                    "state_code": c.get("state_code"), "vintage": vintage,
                    "pulled_at": now}
            hit = latest.get(key)
            if hit is None:
                # non-issuing place — an honest null, not an imputed zero
                rows.append({**base, "permit_source": "none"})
                continue
            prior_units = [p[key]["units_total"] for p in priors if key in p]
            rows.append({**base, "permit_source": "place",
                         **compute_metrics(c.get("population"),
                                           hit["units_total"], hit["u1"],
                                           prior_units)})
        assign_flags(rows)

        # replace-all upsert: the table is a derived cache of one vintage
        for i in range(0, len(rows), 500):
            supabase.table("city_permits").upsert(rows[i:i + 500]).execute()

        covered = [r for r in rows if r["permit_source"] == "place"]
        validation = {}
        for name, state in VALIDATE_MARKETS:
            m = next((r for r in rows if r["city_name"] == name
                      and r["state_code"] == state), None)
            if m:
                validation[f"{name}, {state}"] = {
                    k: m.get(k) for k in ("permit_units_1yr", "permits_pc",
                                          "permit_sf_share", "permit_trend",
                                          "permit_flag", "permit_source")}
        result = {
            "vintage": vintage, "cities": len(rows),
            "covered_place_level": len(covered),
            "match_rate": round(len(covered) / len(rows), 3) if rows else 0,
            "validation_mckinney_vs_cleveland": validation,
            "note": ("context column only — never a grade input; "
                     "if the validation pair looks interchangeable, "
                     "distrust the column (plan §4)"),
        }
        supabase.table("async_jobs").update({
            "status": "complete", "result": result, "completed_at": "now()",
        }).eq("id", job_id).execute()
        logger.info("leadoff_permits.complete", extra={
            "vintage": vintage, "covered": len(covered), "cities": len(rows)})
    except Exception as exc:
        logger.error("leadoff_permits.failed", extra={"job_id": job_id,
                                                      "error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()


def enqueue_due_permits() -> None:
    """Daily scheduler tick: refresh when the store is empty or stale
    (leadoff_permits_refresh_days). Free — 16 small text downloads."""
    from config import settings

    if not settings.leadoff_permits_enabled:
        return
    supabase = get_supabase()
    try:
        newest = (supabase.table("city_permits").select("pulled_at")
                  .order("pulled_at", desc=True).limit(1).execute().data or [])
        if newest:
            pulled = datetime.fromisoformat(
                str(newest[0]["pulled_at"]).replace("Z", "+00:00"))
            if datetime.now(timezone.utc) - pulled < timedelta(
                    days=settings.leadoff_permits_refresh_days):
                return
        pending = (supabase.table("async_jobs").select("id")
                   .eq("job_type", "leadoff_permits")
                   .in_("status", ["pending", "running"]).limit(1)
                   .execute().data or [])
        if pending:
            return
        import uuid

        supabase.table("async_jobs").insert({
            "job_type": "leadoff_permits", "entity_id": str(uuid.uuid4()),
            "payload": {}}).execute()
        logger.info("leadoff_permits.enqueued")
    except Exception as exc:
        logger.warning("leadoff_permits.enqueue_failed", extra={"error": str(exc)})
