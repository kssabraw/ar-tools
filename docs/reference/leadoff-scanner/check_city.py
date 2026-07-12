"""
check_city -- score ANY city on demand (~$0.15-0.20, ~3 min).
Runs the full mini-pipeline for one city: demand/CPC (both keyword forms) ->
demand gate -> SERP supply at 13z -> rankability (reviews + exact-category
with rename aliases) -> economics -> grade vs the national distribution.

Usage (via check_city.ps1 so credentials load):
  check_city.ps1 "Moses Lake" WA
  check_city.ps1 "Bend" OR --capture 0.15 --lead-tier high
"""
import argparse, os, re, sys, time
sys.stdout.reconfigure(encoding="utf-8")
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(r"C:\Users\kssab\OneDrive\Desktop\Projects\GBP Demographics Script")
HERE = Path(__file__).parent
sys.path.insert(0, str(ROOT))
import common as cm  # noqa

MIN_VOL = 20
# GBP category quirks discovered the hard way:
ALIAS_LABEL = {"handyman": "handyman handywoman handyperson"}  # renamed by Google
ALIAS_TO = {"plumbing": "plumber"}          # not selectable; real category = Plumber
STOP = {"service", "services", "company", "contractor", "shop", "store",
        "supplier", "and", "the", "near", "me"}

def norm(s): return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", str(s).lower())).strip()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("city"); ap.add_argument("state")
    ap.add_argument("--capture", type=float, default=0.10)
    ap.add_argument("--lead-tier", choices=["low", "mid", "high"], default="mid")
    a = ap.parse_args()

    cities = pd.read_csv(ROOT / "inputs" / "cities.csv", dtype={"location_code": "string"})
    m = cities[(cities.name.str.lower() == a.city.lower()) &
               (cities.state_code.str.upper() == a.state.upper())]
    if m.empty:
        m = cities[cities.name.str.lower().str.contains(a.city.lower()) &
                   (cities.state_code.str.upper() == a.state.upper())]
    if m.empty:
        sys.exit(f"'{a.city}, {a.state}' not in cities.csv (covers US places >=10k pop). "
                 "Smaller towns need a manual geocode -- ask Claude.")
    r = m.sort_values("population", ascending=False).iloc[0]
    lat, lon, pop = r.latitude, r.longitude, int(r.population)
    lc = str(r.location_code) if pd.notna(r.location_code) and str(r.location_code).strip() \
        not in ("", "<NA>", "nan") else None
    print(f"== {r['name']}, {r.state_code}  (pop {pop:,}) ==")
    client = cm.DataForSEOClient()
    cats = pd.read_csv(ROOT / "inputs" / "categories.csv")

    # ---- 1) demand + CPC (one task, both keyword forms) ----------------------
    demand = {}
    if lc:
        kws = list(cats.category_name) + [c + " near me" for c in cats.category_name]
        posted = client.post("/keywords_data/google_ads/search_volume/task_post",
                             [{"location_code": int(float(lc)), "language_name": "English",
                               "keywords": kws}])
        tid = (posted.get("tasks") or [{}])[0].get("id")
        res = None
        for _ in range(50):
            time.sleep(10)
            got = client.get(f"/keywords_data/google_ads/search_volume/task_get/{tid}")
            t0 = (got.get("tasks") or [{}])[0]
            if t0.get("status_code") == 20000 and t0.get("result") is not None:
                res = t0["result"]; break
        base, near = {}, {}
        for it in (res or []):
            kw = (it.get("keyword") or "").lower()
            (near if kw.endswith(" near me") else base)[
                kw[:-8].strip() if kw.endswith(" near me") else kw] = it
        for c in cats.category_name:
            b, n = base.get(c.lower(), {}), near.get(c.lower(), {})
            demand[c] = {"vol": max(b.get("search_volume") or 0, n.get("search_volume") or 0),
                         "cpc": b.get("cpc") or n.get("cpc")}
        gated = [c for c in cats.category_name if demand[c]["vol"] >= MIN_VOL]
        print(f"demand pulled: {len(gated)} of 100 categories pass vol>={MIN_VOL}")
    else:
        gated = list(cats.category_name)
        print("WARNING: no Google Ads location code -- demand unavailable; "
              "pulling supply for all 100 categories")

    # ---- 2) SERP at 13z per gated category -----------------------------------
    def pull(cat):
        try:
            d = client.post("/serp/google/maps/live/advanced",
                            [{"keyword": cat, "location_coordinate": f"{lat},{lon},13z",
                              "language_code": "en", "device": "desktop", "os": "windows",
                              "depth": 100}])
            items = ((d.get("tasks") or [{}])[0].get("result") or [{}])[0].get("items") or []
        except Exception:
            return cat, None
        n_cat = norm(cat)
        label = ALIAS_LABEL.get(n_cat, ALIAS_TO.get(n_cat, n_cat))
        holders = sum(1 for it in items if norm(it.get("category") or "") == label)
        top5 = items[:5]
        revs = sorted(((it.get("rating") or {}).get("votes_count") or 0 for it in top5),
                      reverse=True)
        toks = [t[:6] for t in re.findall(r"[a-z]+", cat.lower())
                if t not in STOP and len(t) >= 4]
        return cat, {
            "supply": len(items),
            "avg5": round(sum(revs) / len(revs), 1) if revs else 0,
            "rev_win": revs[min(2, len(revs) - 1)] if revs else 0,
            "rating": round(pd.Series([(it.get("rating") or {}).get("value")
                                       for it in top5]).dropna().mean() or 0, 2),
            "namekw": sum(1 for it in top5
                          if any(t in str(it.get("title", "")).lower() for t in toks)),
            "holders": holders}

    field = {}
    with ThreadPoolExecutor(max_workers=15) as ex:
        for f in as_completed([ex.submit(pull, c) for c in gated]):
            cat, v = f.result()
            if v: field[cat] = v
    print(f"SERP pulled: {len(field)} categories")

    # ---- 3) economics + grade -------------------------------------------------
    lv = pd.read_csv(ROOT / "inputs" / "lead_values.csv")
    cpl = dict(zip(lv.category_name, lv[{"low": "cpl_low", "mid": "cpl_mid",
                                         "high": "cpl_high"}[a.lead_tier]]))
    pct = pd.read_csv(HERE / "exp_val_percentiles.csv")
    def grade_of(ev, leads, rankab, leadval):
        if pd.isna(leadval): return "F", 0.0
        p = float((pct.exp_val <= ev).mean()) * 100
        if leads < 5 or rankab < 0.15: p = min(p, 74.9)
        for cut, g in [(99, "A+"), (97, "A"), (94, "B+"), (90, "B"), (75, "C"), (50, "D")]:
            if p >= cut: return g, round(p, 1)
        return "F", round(p, 1)

    rows = []
    for cat, v in field.items():
        vol = demand.get(cat, {}).get("vol")
        leadval = cpl.get(cat)
        leads = round((vol or 0) * a.capture)
        value = leads * leadval if leadval is not None else None
        rankab = round(0.75 / (1 + v["avg5"] / 50) + 0.25 / (1 + v["holders"] / 5), 2)
        ev = round((value or 0) * rankab)
        g, p = grade_of(ev, leads, rankab, leadval)
        rows.append({"grade": g, "natl_pct": p, "exp_val": ev, "value_mo": value,
                     "roi": round(ev / max(v["rev_win"], 10), 1), "rankab": rankab,
                     "category": cat, "vol": vol, "supply": v["supply"],
                     "rev_win": v["rev_win"], "rating": v["rating"],
                     "namekw": v["namekw"], "exact_open": v["holders"]})
    out = pd.DataFrame(rows).sort_values("exp_val", ascending=False)
    pd.set_option("display.width", 220)
    print(f"\n=== {r['name']}, {r.state_code} -- opportunities (graded vs national) ===")
    print(out.head(20).to_string(index=False))
    dest = HERE / "checked_cities"
    dest.mkdir(exist_ok=True)
    fp = dest / f"{norm(r['name']).replace(' ', '_')}_{r.state_code}.csv"
    out.to_csv(fp, index=False)
    print(f"\nsaved -> {fp}")

if __name__ == "__main__":
    main()
