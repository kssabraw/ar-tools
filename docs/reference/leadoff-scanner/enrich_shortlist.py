"""
enrich_shortlist -- the fine pass (Pass 2). Takes a shortlist CSV exported by
report.ps1 (needs city_name, state_code, category columns) and appends the
finalist-only signals:
  RD        - referring domains of top-5 competitor sites ("links to win")
  velocity  - field reviews last 30d vs prior 30d + staleness (60-day window)
  trend     - 12-mo demand curve -> growth + peak months (resolves HOT? flags)

All three cache to Supabase (domain / business / category-city keyed, 90-day
freshness), so repeat competitors and known curves cost nothing next time.

Usage:  enrich_shortlist.ps1 shortlist.csv
"""
import argparse, os, re, sys, time
sys.stdout.reconfigure(encoding="utf-8")
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import pandas as pd
import sqlalchemy
from sqlalchemy import text

ROOT = Path(r"C:\Users\kssab\OneDrive\Desktop\Projects\GBP Demographics Script")
DATA = Path.home() / "market-scanner-data" / "intermediate"
sys.path.insert(0, str(ROOT))
import common as cm  # noqa

FRESH_DAYS = 90
def norm(s): return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", str(s).lower())).strip()

def load_cache(eng, table, key_cols):
    try:
        df = pd.read_sql(f"select * from market_scanner.{table}", eng)
        df["pulled_at"] = pd.to_datetime(df["pulled_at"], utc=True)
        fresh = df[df.pulled_at >= datetime.now(timezone.utc) - timedelta(days=FRESH_DAYS)]
        return {tuple(r[k] for k in key_cols): r for _, r in fresh.iterrows()}
    except Exception:
        return {}

def save_cache(eng, table, rows):
    if rows:
        pd.DataFrame(rows).to_sql(table, eng, schema="market_scanner",
                                  if_exists="append", index=False)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("shortlist")
    a = ap.parse_args()
    sl = pd.read_csv(a.shortlist)
    need = {"city_name", "state_code", "category"}
    if not need <= set(sl.columns):
        sys.exit(f"shortlist needs columns {need}; found {list(sl.columns)}")

    cities = pd.read_csv(ROOT / "inputs" / "cities.csv", dtype={"location_code": "string"})
    cities["k"] = cities.name.map(norm) + "|" + cities.state_code
    ckey = {r.k: r for r in cities.itertuples()}
    cats = pd.read_csv(ROOT / "inputs" / "categories.csv")
    cat_id = {c.lower(): i for c, i in zip(cats.category_name, cats.category_id)}

    sl["_ck"] = sl.city_name.map(norm) + "|" + sl.state_code
    sl["_catid"] = sl.category.str.lower().map(cat_id)
    sl = sl[sl._ck.isin(ckey) & sl._catid.notna()].copy()
    sl["_cityid"] = sl._ck.map(lambda k: ckey[k].city_id)
    print(f"shortlist: {len(sl)} markets across {sl._cityid.nunique()} cities")

    serp = pd.read_csv(DATA / "serp_results.csv")
    serp = serp[serp.rank_position <= 5]
    top5 = {k: g for k, g in serp.groupby(["city_id", "category_id"])}

    client = cm.DataForSEOClient()
    eng = sqlalchemy.create_engine(os.environ["SUPABASE_DB_URL"])
    now = datetime.now(timezone.utc)
    d30, d60 = now - timedelta(days=30), now - timedelta(days=60)

    # ---------- RD (domain-keyed cache) ----------
    domains = set()
    for _, r in sl.iterrows():
        g = top5.get((r._cityid, r._catid))
        if g is not None:
            domains |= {d for d in g.domain.dropna().astype(str).str.strip()
                        if d and d != "nan"}
    rd_cache = load_cache(eng, "domain_backlinks", ["domain"])
    misses = sorted(d for d in domains if (d,) not in rd_cache)
    print(f"RD: {len(domains)} domains, {len(misses)} cache misses "
          f"(~${len(misses)*0.005:.2f})")
    new_rows = []
    for i in range(0, len(misses), 100):
        chunk = misses[i:i+100]
        d = client.post("/backlinks/bulk_referring_domains/live", [{"targets": chunk}])
        for it in ((d.get("tasks") or [{}])[0].get("result") or [{}])[0].get("items") or []:
            new_rows.append({"domain": it.get("target"),
                             "referring_domains": it.get("referring_domains"),
                             "pulled_at": now})
    save_cache(eng, "domain_backlinks", new_rows)
    rd = {r["domain"]: r["referring_domains"] for r in new_rows}
    rd.update({k[0]: v["referring_domains"] for k, v in rd_cache.items()})

    # ---------- velocity (business-keyed cache, 60-day window) ----------
    biz = {}
    for _, r in sl.iterrows():
        g = top5.get((r._cityid, r._catid))
        if g is None: continue
        c = ckey[r._ck]
        for name in g.business_name.dropna().unique():
            biz[(norm(name), int(r._cityid))] = (name, c.latitude, c.longitude)
    v_cache = load_cache(eng, "business_reviews", ["biz_key"])
    v_misses = {k: v for k, v in biz.items() if (f"{k[0]}|{k[1]}",) not in v_cache}
    print(f"velocity: {len(biz)} businesses, {len(v_misses)} cache misses "
          f"(~${len(v_misses)*0.0023:.2f})")

    vel_rows = []
    def vel(item):
        (nk, cid), (name, lat, lon) = item
        try:
            p = client.post("/business_data/google/reviews/task_post",
                            [{"keyword": name, "location_coordinate": f"{lat},{lon}",
                              "language_code": "en", "depth": 30, "sort_by": "newest"}])
            tid = (p.get("tasks") or [{}])[0].get("id")
            for _ in range(40):
                time.sleep(8)
                got = client.get(f"/business_data/google/reviews/task_get/{tid}")
                t0 = (got.get("tasks") or [{}])[0]
                if t0.get("status_code") == 20000 and t0.get("result"):
                    items = ((t0.get("result") or [{}])[0] or {}).get("items") or []
                    break
            else:
                return None
        except Exception:
            return None
        dts = []
        for it in items:
            try:
                dts.append(datetime.fromisoformat(
                    str(it.get("timestamp")).replace(" +00:00", "+00:00")))
            except Exception:
                pass
        return {"biz_key": f"{nk}|{cid}",
                "last30": sum(1 for d in dts if d >= d30),
                "prior30": sum(1 for d in dts if d60 <= d < d30),
                "newest": max(dts).date().isoformat() if dts else None,
                "capped": len(items) >= 30 and bool(dts) and min(dts) >= d60,
                "pulled_at": now}
    with ThreadPoolExecutor(max_workers=12) as ex:
        for f in as_completed([ex.submit(vel, it) for it in v_misses.items()]):
            r0 = f.result()
            if r0: vel_rows.append(r0)
    save_cache(eng, "business_reviews", vel_rows)
    vmap = {r["biz_key"]: r for r in vel_rows}
    vmap.update({k[0]: dict(v) for k, v in v_cache.items()})

    # ---------- trend (city+category cache; one keyword task per city) --------
    # ⚠ COORDINATED CACHE CONTRACT (2026-07-12, matches the ar-tools app's
    # services/leadoff_actions.py): pulls are now 24 months (date_from) so the
    # ADDITIVE growth_yoy_ss field (same-month YoY — trailing 3 months vs the
    # same calendar months a year earlier, the lesson-#8 seasonality fix) can
    # be computed. growth_yoy keeps its legacy 12-month-window semantics
    # UNCHANGED (the [:12] slices below take the most recent 12 of the 24).
    # Do NOT redefine growth_yoy — both toolchains write this table.
    t_cache = load_cache(eng, "demand_trend", ["trend_key"])
    by_city = sl.groupby("_cityid")
    trend_rows = []
    TREND_MONTHS = 24
    date_from = f"{(now.year * 12 + now.month - 1 - TREND_MONTHS) // 12:04d}-" \
                f"{(now.year * 12 + now.month - 1 - TREND_MONTHS) % 12 + 1:02d}-01"
    for cid, g in by_city:
        c = ckey[g._ck.iloc[0]]
        lc = str(c.location_code) if str(c.location_code) not in ("", "nan", "<NA>", "None") else None
        want = [cat for cat in g.category.unique()
                if (f"{cid}|{norm(cat)}",) not in t_cache]
        if not lc or not want: continue
        kws = list(want) + [w + " near me" for w in want]
        p = client.post("/keywords_data/google_ads/search_volume/task_post",
                        [{"location_code": int(float(lc)), "language_name": "English",
                          "keywords": kws, "date_from": date_from}])
        tid = (p.get("tasks") or [{}])[0].get("id")
        res = None
        for _ in range(40):
            time.sleep(10)
            got = client.get(f"/keywords_data/google_ads/search_volume/task_get/{tid}")
            t0 = (got.get("tasks") or [{}])[0]
            if t0.get("status_code") == 20000 and t0.get("result") is not None:
                res = t0["result"]; break
        monthly = {}
        for it in (res or []):
            kw = (it.get("keyword") or "").lower().replace(" near me", "").strip()
            ms = it.get("monthly_searches") or []
            if ms and (kw not in monthly or len(ms) > len(monthly[kw])):
                monthly[kw] = ms
        def same_month_growth(ms):
            # same-month YoY: 3 most recent (year,month) vs the same months a
            # year earlier; refuses on any missing prior-year month (a partial
            # match would reintroduce the seasonal confound).
            by_ym = {(m.get("year"), m.get("month")): (m.get("search_volume") or 0)
                     for m in ms if m.get("year") is not None}
            recent = sorted(by_ym, reverse=True)[:3]
            if len(recent) < 3: return None
            prior = [(y - 1, mo) for y, mo in recent]
            if any(k not in by_ym for k in prior): return None
            top, bot = sum(by_ym[k] for k in recent), sum(by_ym[k] for k in prior)
            return round(top / bot, 2) if bot else None

        for cat in want:
            ms = monthly.get(cat.lower(), [])
            vals = [m.get("search_volume") or 0 for m in ms][:12]
            if len(vals) >= 6:
                recent, old = sum(vals[:3]) / 3, sum(vals[-3:]) / 3
                growth = round(recent / old, 2) if old else None
                peaks = sorted(ms[:12], key=lambda m: -(m.get("search_volume") or 0))[:2]
                peak = ",".join(str(m.get("month")) for m in peaks)
            else:
                growth, peak = None, None
            trend_rows.append({"trend_key": f"{cid}|{norm(cat)}", "growth_yoy": growth,
                               "growth_yoy_ss": same_month_growth(ms),
                               "peak_months": peak, "pulled_at": now})
    save_cache(eng, "demand_trend", trend_rows)
    tmap = {r["trend_key"]: r for r in trend_rows}
    tmap.update({k[0]: dict(v) for k, v in t_cache.items()})
    print(f"trend: {len(trend_rows)} fresh pulls, rest cached")

    # ---------- assemble ----------
    def enrich(r):
        g = top5.get((r._cityid, r._catid))
        rds, l30, p30, newest = [], 0, 0, []
        if g is not None:
            for _, b in g.iterrows():
                d = str(b.domain).strip()
                if d and d != "nan" and d in rd: rds.append(rd[d])
                v = vmap.get(f"{norm(b.business_name)}|{int(r._cityid)}")
                if v:
                    l30 += v["last30"] or 0; p30 += v["prior30"] or 0
                    if v["newest"]: newest.append(str(v["newest"]))
        t = tmap.get(f"{r._cityid}|{norm(r.category)}", {})
        mom = ("accel" if l30 > p30 * 1.3 else "cooling" if l30 < p30 * 0.7
               else "steady") if (l30 or p30) else "dead"
        return pd.Series({
            "rd_min": min(rds) if rds else None, "rd_med": int(pd.Series(rds).median()) if rds else None,
            "field_vel30": l30, "field_prior30": p30, "momentum": mom,
            "newest_review": max(newest) if newest else None,
            "growth_yoy": t.get("growth_yoy"),
            "growth_yoy_ss": t.get("growth_yoy_ss"),
            "peak_months": t.get("peak_months")})
    out = pd.concat([sl.drop(columns=["_ck", "_catid", "_cityid"]),
                     sl.apply(enrich, axis=1)], axis=1)
    dest = Path(a.shortlist).with_name(Path(a.shortlist).stem + "_enriched.csv")
    out.to_csv(dest, index=False)
    pd.set_option("display.width", 240)
    show = [c for c in ["grade", "city_name", "state_code", "category", "exp_val",
                        "rd_min", "field_vel30", "field_prior30", "momentum",
                        "newest_review", "growth_yoy", "peak_months"] if c in out.columns]
    print(f"\n=== enriched ===\n{out[show].to_string(index=False)}")
    print(f"\nsaved -> {dest}")

if __name__ == "__main__":
    main()
