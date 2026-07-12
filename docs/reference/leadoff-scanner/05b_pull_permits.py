"""
05b_pull_permits -- Census Building Permits Survey (BPS) "prospect pipeline"
column for the LeadOff board. FREE (keyless flat files -- CENSUS_API_KEY not
needed; place-level BPS is not in the Census Data API at all).

Spec + design rulings: ar-tools docs/modules/leadoff-permits-plan-v1_0.md.
Context column ONLY -- never touches build_score/grade (no frankenscore).

⚠ Authored in the cloud session (which cannot reach census.gov) -- run
--validate FIRST and eyeball; the BPS file layout has vintage quirks (two
header rows, column naming drift) and the parser fails loudly rather than
guessing.

Usage (scanner project root, no creds needed):
  python 05b_pull_permits.py --validate     # McKinney TX vs Cleveland OH only
  python 05b_pull_permits.py                # full: all cities, latest yr + 3 prior
  python 05b_pull_permits.py --force        # ignore cached downloads

Pipeline conventions: JSON checkpoint (checkpoints/permits.json), plain-ASCII
permits_status.txt, idempotent downloads under market-scanner-data/permits/.
Output: intermediate/permits.csv (city_id + the six contract columns) +
permits_board_update.sql (in-place ALTER+UPDATE variant for leadoff_board).
"""
import argparse, io, json, re, sys, urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
import pandas as pd

ROOT = Path(r"C:\Users\kssab\OneDrive\Desktop\Projects\GBP Demographics Script")
DATA = Path.home() / "market-scanner-data"
PERMITS_DIR = DATA / "permits"
CHECKPOINT = DATA / "checkpoints" / "permits.json"
STATUS = DATA / "permits_status.txt"

BASE = "https://www2.census.gov/econ/bps/Place"
REGIONS = {"ne": "Northeast", "mw": "Midwest", "so": "South", "we": "West"}
# state -> BPS region file prefix (Census regions)
STATE_REGION = {
    **{s: "ne" for s in "CT ME MA NH RI VT NJ NY PA".split()},
    **{s: "mw" for s in "IL IN MI OH WI IA KS MN MO NE ND SD".split()},
    **{s: "so" for s in "DE FL GA MD NC SC VA WV DC AL KY MS TN AR LA OK TX".split()},
    **{s: "we" for s in "AZ CO ID MT NV NM UT WY AK CA HI OR WA".split()},
}
VALIDATE_MARKETS = [("McKinney", "TX"), ("Cleveland", "OH")]
TREND_BASE_YEARS = 3
HOT_TREND, COLD_TREND = 1.2, 0.8


def status(msg):
    print(msg)
    with open(STATUS, "a", encoding="ascii", errors="replace") as f:
        f.write(msg + "\n")


def norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", str(s).lower())).strip()


def norm_place(s):
    """BPS place names carry type suffixes ('McKinney city') -- strip the
    common ones so they match cities.csv names."""
    n = norm(s)
    return re.sub(r"\s+(city|town|village|borough|township|cdp)$", "", n).strip()


def fetch(url, dest, force=False):
    if dest.exists() and not force:
        return dest.read_bytes()
    status(f"GET {url}")
    with urllib.request.urlopen(url, timeout=120) as r:
        raw = r.read()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)
    return raw


def latest_vintage(probe_region="we", start=None):
    """Newest year whose annual file exists (probe current year, step back)."""
    import datetime
    y = start or datetime.date.today().year
    for year in range(y, y - 4, -1):
        try:
            urllib.request.urlopen(f"{BASE}/{REGIONS[probe_region]}/{probe_region}{year}a.txt",
                                   timeout=30).close()
            return year
        except Exception:
            continue
    sys.exit("no BPS annual file found in the last 4 years -- check the URL scheme")


def parse_bps(raw):
    """BPS annual place files: TWO header rows to combine, then CSV rows.
    Column names drift across vintages -- match by keyword and fail loudly."""
    text = raw.decode("latin-1")
    lines = text.splitlines()
    h1, h2 = lines[0].split(","), lines[1].split(",")
    if len(h2) < len(h1):
        h2 += [""] * (len(h1) - len(h2))
    cols = [f"{a.strip()} {b.strip()}".strip() for a, b in zip(h1, h2)]
    df = pd.read_csv(io.StringIO("\n".join(lines[2:])), names=cols,
                     dtype=str, on_bad_lines="skip")

    def find(*kws, forbid=()):
        for c in df.columns:
            lc = c.lower()
            if all(k in lc for k in kws) and not any(f in lc for f in forbid):
                return c
        sys.exit(f"BPS layout drift: no column matching {kws} "
                 f"(have: {list(df.columns)[:20]}...) -- update parse_bps")

    # imputed estimates section = the plain 'Units' columns (the 'reported
    # only' section is labeled 'rep'); adjust here if a vintage differs.
    out = pd.DataFrame({
        "state_fips": df[find("state", "code")].str.strip().str.zfill(2),
        "place_name": df[find("place", "name")].str.strip(),
        "u1": pd.to_numeric(df[find("1-unit", "units", forbid=("rep",))], errors="coerce"),
        "u2": pd.to_numeric(df[find("2-unit", "units", forbid=("rep",))], errors="coerce"),
        "u34": pd.to_numeric(df[find("3-4", "units", forbid=("rep",))], errors="coerce"),
        "u5": pd.to_numeric(df[find("5", "units", forbid=("rep",))], errors="coerce"),
    })
    out["units_total"] = out[["u1", "u2", "u34", "u5"]].fillna(0).sum(axis=1)
    return out


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


def year_frame(year, regions, force):
    frames = []
    for reg in sorted(set(regions)):
        raw = fetch(f"{BASE}/{REGIONS[reg]}/{reg}{year}a.txt",
                    PERMITS_DIR / f"{reg}{year}a.txt", force)
        frames.append(parse_bps(raw))
    df = pd.concat(frames, ignore_index=True)
    df["k"] = df["state_fips"] + "|" + df["place_name"].map(norm_place)
    # a place can appear once per file; keep max units on dupes (rare)
    return df.groupby("k", as_index=False).agg(
        units_total=("units_total", "max"), u1=("u1", "max"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    STATUS.unlink(missing_ok=True)

    cities = pd.read_csv(ROOT / "inputs" / "cities.csv")
    if a.validate:
        keep = pd.concat([
            cities[(cities.name.str.lower() == c.lower()) &
                   (cities.state_code == s)] for c, s in VALIDATE_MARKETS])
        if len(keep) < len(VALIDATE_MARKETS):
            sys.exit("validate market missing from cities.csv")
        cities = keep
    cities = cities.copy()
    cities["k"] = cities.state_code.map(STATE_FIPS) + "|" + cities.name.map(norm)
    regions = [STATE_REGION[s] for s in cities.state_code.unique() if s in STATE_REGION]

    latest = latest_vintage(regions[0])
    status(f"latest BPS vintage: {latest}")
    cur = year_frame(latest, regions, a.force).set_index("k")
    prior = [year_frame(latest - i, regions, a.force).set_index("k")
             for i in range(1, TREND_BASE_YEARS + 1)]

    rows = []
    for _, c in cities.iterrows():
        hit = cur.loc[c.k] if c.k in cur.index else None
        if hit is None:
            rows.append({"city_id": c.city_id, "permit_source": "none"})
            continue
        units = float(hit.units_total)
        base_vals = [float(p.loc[c.k].units_total) for p in prior if c.k in p.index]
        base = sum(base_vals) / len(base_vals) if base_vals else None
        rows.append({
            "city_id": c.city_id,
            "permit_units_1yr": round(units),
            "permits_pc": round(units / c.population * 1000, 2) if c.population else None,
            "permit_sf_share": round(float(hit.u1) / units, 2) if units else None,
            "permit_trend": round(units / base, 2) if base else None,
            "permit_source": "place",
        })
    out = pd.DataFrame(rows)

    matched = out[out.permit_source == "place"]
    status(f"match rate: {len(matched)}/{len(out)} cities via place file "
           f"(unmatched are non-issuing places -- county fallback is a "
           f"phase-2 follow-up needing a county-FIPS map; nulls are honest)")

    if len(matched) >= 10:  # flags need a distribution; skip in validate mode
        p90 = matched.permits_pc.quantile(0.9)
        p10 = matched.permits_pc.quantile(0.1)
        out["permit_flag"] = "-"
        out.loc[(out.permits_pc >= p90) & (out.permit_trend >= HOT_TREND),
                "permit_flag"] = "HOT-pipeline"
        out.loc[(out.permits_pc <= p10) & (out.permit_trend <= COLD_TREND),
                "permit_flag"] = "COLD-pipeline"

    if a.validate:
        show = out.merge(cities[["city_id", "name", "state_code", "population"]],
                         on="city_id")
        print("\n=== VALIDATION (expect the boomtown to dwarf the rust-belt "
              "city per-capita, trend >= 1) ===")
        print(show.to_string(index=False))
        print("\nIf these two look interchangeable, STOP -- the signal isn't "
              "separating reality and the column shouldn't ship.")
        return

    dest = DATA / "intermediate" / "permits.csv"
    out.to_csv(dest, index=False)
    status(f"saved -> {dest}")
    sql = dest.with_name("permits_board_update.sql")
    with open(sql, "w", encoding="ascii") as f:
        f.write("-- in-place variant (loader reload also works; re-check "
                "service_role grants after any reload)\n")
        for col, typ in [("permit_units_1yr", "bigint"), ("permits_pc", "double precision"),
                         ("permit_sf_share", "double precision"),
                         ("permit_trend", "double precision"),
                         ("permit_flag", "text"), ("permit_source", "text")]:
            f.write(f"alter table market_scanner.leadoff_board add column if not exists {col} {typ};\n")
        f.write("-- then bulk UPDATE from permits.csv via the loader's copy pattern\n")
    status(f"saved -> {sql}")
    CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
    CHECKPOINT.write_text(json.dumps({"vintage": latest, "rows": len(out)}))
    status("done")


if __name__ == "__main__":
    main()
