"""
Market-scanner report tool. Query the finished scan with simple filters --
no SQL needed. Run via report.ps1 so credentials load first.

Defaults to the current run (run_id=3): the corrected 13z supply, dual-form
demand, and the v2 opportunity score. Only supply-measured markets are shown
unless --include-unmeasured is passed.

Examples:
  report.ps1                                   # top 20 opportunities (v2)
  report.ps1 --category plumber                # best cities for plumbers
  report.ps1 --state FL                         # best opportunities in Florida
  report.ps1 --city "The Villages"             # every category for one city
  report.ps1 --category hvac --state TX --limit 30
  report.ps1 --class "Best opportunity"
  report.ps1 --min-demand 200                   # only strong-demand markets
  report.ps1 --max-supply 8 --min-pop 100000    # weak competition in big cities
  report.ps1 --trades                           # best city per common trade
  report.ps1 --include-thin                      # include low-coverage categories
  report.ps1 --include-unmeasured                # include below-demand-gate combos
  report.ps1 --run 2                             # query a different run_id
  report.ps1 --category hvac --csv hvac.csv      # also save results to CSV
"""
import argparse, os, sys
import pandas as pd
import sqlalchemy

pd.set_option("display.width", 240); pd.set_option("display.max_columns", 40)
pd.set_option("display.max_colwidth", 44); pd.set_option("display.max_rows", 200)

ROOT = r"C:\Users\kssab\OneDrive\Desktop\Projects\GBP Demographics Script"
T = "market_scanner.market_opportunity_master"
DEFAULT_RUN = 3
SCORE = "opportunity_score_v3"   # rankability(review-strength + exact-category) + demand + CPC
TRADES = ["plumber", "hvac", "air conditioning contractor", "roofing contractor",
          "electrician", "tree service", "landscaper", "house painter",
          "garage door", "concrete contractor", "fence contractor", "pest control"]


def main():
    ap = argparse.ArgumentParser(description="Market opportunity reports (v2 score, run_id=3)")
    ap.add_argument("--category", help="category name contains (e.g. plumber, hvac)")
    ap.add_argument("--state", help="2-letter state code (e.g. FL, TX)")
    ap.add_argument("--city", help="city name contains")
    ap.add_argument("--class", dest="klass",
                    help='classification: "Best opportunity", "Competitive but lucrative", '
                         '"Real but modest opportunity", "Low value"')
    ap.add_argument("--min-pop", type=int, default=0, help="minimum city population")
    ap.add_argument("--min-demand", type=int, help="minimum monthly search demand")
    ap.add_argument("--max-supply", type=int, help="max competitors (find weak markets)")
    ap.add_argument("--min-supply", type=int, help="min competitors")
    ap.add_argument("--limit", type=int, default=20, help="rows to show (default 20)")
    ap.add_argument("--run", type=int, default=DEFAULT_RUN, help="run_id (default 3)")
    ap.add_argument("--capture", type=float, default=0.10,
                    help="share of monthly searches converted to leads (default 0.10)")
    ap.add_argument("--lead-tier", choices=["low", "mid", "high"], default="mid",
                    help="lead-value tier from lead_values.csv (default mid)")
    ap.add_argument("--sort", choices=["build", "roi", "leads", "v3", "expected",
                                       "value", "demand"],
                    default="build",
                    help="build=Build Score/grade (default, $-weighted); "
                         "roi=$/mo per review of effort, the WPA stat (win cheapest); "
                         "leads=expected leads/mo (goal = lead volume); "
                         "v3=within-category rankability; expected=$/mo x win-likelihood; "
                         "value=$/mo; demand=searches")
    ap.add_argument("--include-thin", action="store_true",
                    help="include low-coverage (thin-data) categories, hidden by default")
    ap.add_argument("--include-unmeasured", action="store_true",
                    help="include below-demand-gate combos (no competition measured)")
    ap.add_argument("--trades", action="store_true",
                    help="summary: best city for each common trade")
    ap.add_argument("--csv", help="also write results to this CSV file")
    a = ap.parse_args()

    url = os.environ.get("SUPABASE_DB_URL")
    if not url:
        sys.exit("SUPABASE_DB_URL not set -- run this via report.ps1, not python directly.")

    cats = pd.read_csv(ROOT + r"\inputs\categories.csv")
    id2name = dict(zip(cats["category_id"], cats["category_name"]))

    eng = sqlalchemy.create_engine(url)
    cols = (f"city_id, city_name, state_code, population, category_id, {SCORE}, "
            "supply_count, supply_measured, category_cpc, category_cpc_nearme, "
            "demand_vol, exact_cat_holders, avg_top5_reviews, classification, low_coverage")
    where = f"run_id={a.run}"
    if not a.include_unmeasured:
        where += " and supply_measured is true"
    with eng.connect() as c:
        df = pd.read_sql(f"select {cols} from {T} where {where}", c)
    if df.empty:
        sys.exit(f"No rows for run_id={a.run}. Try --run 2 or check the load.")
    df["category"] = df["category_id"].map(id2name).fillna(df["category_id"])
    df["cpc_eff"] = df["category_cpc"].fillna(df["category_cpc_nearme"])
    df["score"] = pd.to_numeric(df[SCORE], errors="coerce")

    # --- xDemand (the xFIP move) --------------------------------------------
    # Observed demand is noisy: Google buckets volumes and occasionally reports
    # wild outliers (datacenter towns etc). Regress toward the category's
    # population-expected demand: winsorize extreme observations to 4x the
    # expectation, then blend 75% observed / 25% expected.
    obs = pd.to_numeric(df["demand_vol"], errors="coerce")
    rate = (obs / df["population"]).replace([float("inf")], pd.NA)
    cat_rate = rate.groupby(df["category_id"]).transform("median")
    expected = (cat_rate * df["population"]).fillna(obs)
    wins = obs.clip(upper=4 * expected)
    df["xdemand"] = (0.75 * wins.fillna(expected) + 0.25 * expected).round()
    # BABIP-style luck flag: observed vs demographically-expected demand.
    # Doesn't change the score (xdemand already regresses it) — it tells you
    # whether a market's numbers are fragile. HOT? = running >=2x expectation
    # (verify: real trend or measurement luck). COLD? = <=0.5x (possibly
    # undervalued, or something is off about the place).
    dem_ratio = (obs / expected.replace(0, pd.NA)).astype(float)
    df["dem_ratio"] = dem_ratio.round(2)
    # park adjustment: a city where EVERY category runs hot (metro-suburb
    # spillover etc) isn't luck — flag only deviation from the CITY's own norm.
    city_norm = dem_ratio.groupby([df["city_name"], df["state_code"]]).transform("median")
    rel = dem_ratio / city_norm.replace(0, pd.NA)
    df["luck"] = "-"
    df.loc[rel >= 2, "luck"] = "HOT?"
    df.loc[rel <= 0.5, "luck"] = "COLD?"

    # lead economics: est leads/mo = xdemand x capture; est $/mo = leads x lead-value
    lv = pd.read_csv(ROOT + r"\inputs\lead_values.csv")
    cat2lead = dict(zip(lv["category_name"], lv[{"low": "cpl_low", "mid": "cpl_mid",
                                                 "high": "cpl_high"}[a.lead_tier]]))
    df["lead_value"] = df["category"].map(cat2lead)
    df["est_leads_mo"] = (df["xdemand"].fillna(0) * a.capture).round().astype("Int64")
    df["est_value_mo"] = (df["est_leads_mo"] * df["lead_value"]).round().astype("Int64")

    # rankability factor (0-1 win-likelihood): 0.75 field-weakness + 0.25 open-exact-category
    rf = 1 / (1 + pd.to_numeric(df["avg_top5_reviews"], errors="coerce").fillna(0) / 50)
    ef = 1 / (1 + df["exact_cat_holders"].fillna(0).astype(float) / 5)
    df["rankability"] = (0.75 * rf + 0.25 * ef).round(2)
    # expected value = money-if-you-rank x how-likely-you-rank (cross-category, absolute)
    df["exp_value_mo"] = (df["est_value_mo"].fillna(0).astype(float)
                          * df["rankability"]).round().astype("Int64")
    # expected LEADS = leads-if-you-rank x win-likelihood — the "on-base" stat.
    # Use when the goal is lead volume; exp_value weights leads by $ (the OPS stat).
    df["exp_leads_mo"] = (df["est_leads_mo"].fillna(0).astype(float)
                          * df["rankability"]).round().astype("Int64")
    # national percentile of expected value (computed pre-filter, so it's stable:
    # "top X% of ALL measured markets"). Same ordering as $, adds context.
    df["exp_pct"] = (100 * df["exp_value_mo"].astype(float).rank(pct=True)).round(1)

    # BUILD SCORE: the one-number decision metric. exp_pct with guardrail vetoes
    # baked in so nobody has to eyeball rankability/volume/value separately:
    #   - <5 leads/mo -> capped at C (too small to matter, however winnable)
    #   - rankability <0.15 -> capped at C (field too brutal, however lucrative)
    #   - no lead value -> F
    bs = df["exp_pct"].copy()
    capped = (df["est_leads_mo"].fillna(0) < 5) | (df["rankability"] < 0.15)
    bs[capped] = bs[capped].clip(upper=74.9)
    bs[df["lead_value"].isna()] = 0.0
    df["build_score"] = bs.round(1)
    df["grade"] = pd.cut(df["build_score"], right=False,
                         bins=[0, 50, 75, 90, 94, 97, 99, 101],
                         labels=["F", "D", "C", "B", "B+", "A", "A+"]).astype(str)

    # --- WPA layer: field quality (precomputed from SERP top-5, $0) ----------
    fq = pd.read_csv(ROOT + r"\inputs\field_quality.csv")
    df = df.merge(fq, on=["city_id", "category_id"], how="left")
    # ROI = $/mo per review of effort. rev_to_win floored at 10 (a credible
    # profile always needs some reviews) so tiny fields don't divide-by-zero.
    df["roi"] = (df["exp_value_mo"].fillna(0).astype(float)
                 / df["rev_to_win"].fillna(10).clip(lower=10)).round(1)
    # confidence: Google buckets small volumes coarsely -> wide error bars
    df["conf"] = pd.cut(df["xdemand"].fillna(0), right=False,
                        bins=[0, 50, 260, 10**9],
                        labels=["low", "med", "high"]).astype(str)

    if not a.include_thin:
        df = df[~df["low_coverage"].astype("boolean").fillna(False)]

    if a.trades:
        rows = []
        for kw in TRADES:
            m = df[df["category"].str.lower().str.contains(kw, na=False)]
            m = m.dropna(subset=["score"])
            if len(m):
                r = m.sort_values("score", ascending=False).iloc[0]
                rows.append((r["category"], f'{r["city_name"]}, {r["state_code"]}',
                             round(r["score"], 1), int(r["supply_count"]),
                             int(r["demand_vol"]) if pd.notna(r["demand_vol"]) else None,
                             round(r["cpc_eff"], 2) if pd.notna(r["cpc_eff"]) else None))
        out = pd.DataFrame(rows, columns=["category", "best_city", "score", "supply",
                                          "demand", "cpc"]).drop_duplicates("category")
        _emit(out, a.csv); return

    if a.category: df = df[df["category"].str.lower().str.contains(a.category.lower(), na=False)]
    if a.state:    df = df[df["state_code"].str.upper() == a.state.upper()]
    if a.city:     df = df[df["city_name"].str.lower().str.contains(a.city.lower(), na=False)]
    if a.klass:    df = df[df["classification"] == a.klass]
    if a.min_pop:  df = df[df["population"] >= a.min_pop]
    if a.min_demand is not None: df = df[df["demand_vol"].fillna(0) >= a.min_demand]
    if a.max_supply is not None: df = df[df["supply_count"] <= a.max_supply]
    if a.min_supply is not None: df = df[df["supply_count"] >= a.min_supply]

    df = df.dropna(subset=["score"])
    sort_col = {"build": "build_score", "roi": "roi", "leads": "exp_leads_mo",
                "v3": "score", "expected": "exp_value_mo", "value": "est_value_mo",
                "demand": "demand_vol"}[a.sort]
    df = df.sort_values(sort_col, ascending=False).head(a.limit)
    out = df.assign(build=df["build_score"],
                    v3=df["score"].round(1),
                    exp_val=df["exp_value_mo"],
                    value_mo=df["est_value_mo"],
                    rankab=df["rankability"],
                    xdem=df["xdemand"].astype("Int64"),
                    rev_win=df["rev_to_win"].astype("Int64"),
                    rating=df["top5_rating"],
                    namekw=df["name_match"].astype("Int64"),
                    exact_open=df["exact_cat_holders"].astype("Int64"))
    out = out[["grade", "luck", "conf", "build", "roi", "exp_val", "value_mo", "rankab",
               "city_name", "state_code", "category", "xdem", "rev_win", "rating",
               "namekw", "exact_open", "v3", "city_id", "category_id", "population"]]
    _emit(out, a.csv)


def _emit(out, csv):
    if out.empty:
        print("No rows match those filters."); return
    print(f"\n{len(out)} rows:\n")
    print(out.to_string(index=False))
    if csv:
        out.to_csv(csv, index=False); print(f"\nSaved -> {csv}")


if __name__ == "__main__":
    main()
