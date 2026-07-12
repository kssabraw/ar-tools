"""
proximity_prototype -- FREE feasibility test for the LeadOff proximity signal
(the unmodeled Distance pillar). Runs DESKTOP-SIDE because that's where the
addresses live (serp_results.csv kept an `address` column; the loaded Supabase
serp_top5 did not). Uses the free US Census batch geocoder -- no DataForSEO
spend. Spec: ar-tools docs/modules/leadoff-proximity-plan-v1_0.md §5 option 0.

What it does, for the two test markets (La Jolla plumber/locksmith/landscape
architect + KC locksmith):
  1. pulls each market's competitor rows from serp_results.csv,
  2. reconstructs "<address>, <city>, <state>" using cities.csv (city_id -> place),
  3. batch-geocodes via the Census Geocoder (10k/request, keyless -- the
     onelineaddress/batch endpoint; CENSUS_API_KEY not even required here),
  4. computes octant coverage around the city centroid (prominence-weighted,
     distance-decayed -- the §2 method), and prints the underserved octants.

Eyeball test: does the underserved-zone read match known geography? (La Jolla's
field should lean toward central San Diego, leaving the coast/north underserved.)
If the sub-zone signal is real, proximity is worth building; if street-centroid
coarseness blurs it on the dense markets, that's the earned case for the $137
exact-pin pull (plan §5 option D).

Usage (scanner project root):
  python proximity_prototype.py
"""
import csv, io, math, sys, time, urllib.request, urllib.parse
sys.stdout.reconfigure(encoding="utf-8")
from pathlib import Path
import pandas as pd

ROOT = Path(r"C:\Users\kssab\OneDrive\Desktop\Projects\GBP Demographics Script")
DATA = Path.home() / "market-scanner-data" / "intermediate"
SERP_CSV = DATA / "serp_results.csv"
CENSUS_BATCH = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"

# (city_name, state, category_id) -- the known test markets
TEST_MARKETS = [
    ("La Jolla", "CA", "plumber"),
    ("La Jolla", "CA", "locksmith"),
    ("La Jolla", "CA", "landscape_architect"),
    ("Kansas City", "MO", "locksmith"),
]
OCTANTS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def bearing(lat1, lon1, lat2, lon2):
    f1, f2, dl = map(math.radians, (lat1, lat2, lon2 - lon1))
    y = math.sin(dl) * math.cos(f2)
    x = math.cos(f1) * math.sin(f2) - math.sin(f1) * math.cos(f2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def dist_mi(lat1, lon1, lat2, lon2):
    f1, f2 = math.radians(lat1), math.radians(lat2)
    df, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(df / 2) ** 2 + math.cos(f1) * math.cos(f2) * math.sin(dl / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(a))


def octant(b):
    return OCTANTS[int(((b + 22.5) % 360) // 45)]


def census_batch_geocode(rows):
    """rows: list of (unique_id, one_line_address). Returns {id: (lat, lon)}.
    Census batch takes CSV: id,street,city,state,zip -- but the onelineaddress
    batch accepts id,address. We POST as multipart file 'addressFile'."""
    buf = io.StringIO()
    w = csv.writer(buf)
    for rid, addr in rows:
        w.writerow([rid, addr])
    body = buf.getvalue().encode()
    boundary = "----leadoffproximity"
    payload = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="benchmark"\r\n\r\nPublic_AR_Current\r\n'
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="addressFile"; filename="a.csv"\r\n'
        "Content-Type: text/csv\r\n\r\n"
    ).encode() + body + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        CENSUS_BATCH, data=payload,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        out = r.read().decode("latin-1")
    coords = {}
    for row in csv.reader(io.StringIO(out)):
        # id, input, match_flag, match_type, matched_addr, lon_lat, ...
        if len(row) >= 6 and row[2] == "Match":
            try:
                lon, lat = map(float, row[5].split(","))
                coords[row[0]] = (lat, lon)
            except (ValueError, IndexError):
                pass
    return coords


def main():
    if not SERP_CSV.exists():
        sys.exit(f"{SERP_CSV} not found")
    cities = pd.read_csv(ROOT / "inputs" / "cities.csv")
    serp = pd.read_csv(SERP_CSV, dtype={"category_id": str})

    for city_name, state, cat in TEST_MARKETS:
        crow = cities[(cities.name.str.lower() == city_name.lower())
                      & (cities.state_code == state)]
        if crow.empty:
            print(f"skip {city_name},{state}: not in cities.csv"); continue
        crow = crow.iloc[0]
        cid, clat, clon = crow.city_id, crow.latitude, crow.longitude
        g = serp[(serp.city_id == cid) & (serp.category_id == cat)]
        g = g[g.address.notna() & (g.address.astype(str).str.strip() != "")]
        if g.empty:
            print(f"\n== {city_name}, {state} {cat}: no addressed competitors =="); continue

        rows = [(str(i), f"{r.address}, {city_name}, {state}")
                for i, r in g.iterrows()]
        coords = census_batch_geocode(rows)
        time.sleep(1)

        cov = {o: 0.0 for o in OCTANTS}
        placed = 0
        print(f"\n== {city_name}, {state} -- {cat} "
              f"({len(coords)}/{len(rows)} geocoded) ==")
        for i, r in g.iterrows():
            ll = coords.get(str(i))
            if not ll:
                continue
            placed += 1
            b = bearing(clat, clon, ll[0], ll[1])
            d = dist_mi(clat, clon, ll[0], ll[1])
            rev = float(r.review_count) if pd.notna(r.review_count) else 0
            cov[octant(b)] += rev / (1 + d / 2)
        if not placed:
            print("  no geocoded competitors"); continue
        mx = max(cov.values()) or 1
        for o, v in sorted(cov.items(), key=lambda kv: -kv[1]):
            bar = "#" * int(30 * v / mx)
            print(f"  {o:3s} {v:7.1f}  {bar}")
        empty = [o for o, v in cov.items() if v == 0]
        print(f"  UNDERSERVED (empty octants): {', '.join(empty) or 'none'}")
    print("\nEyeball: do the empty/weak octants match the market's real geography? "
          "If yes, the signal is real -> build it. If street-centroid noise blurs "
          "dense markets, that's the case for the $137 exact-pin pull (plan §5 D).")


if __name__ == "__main__":
    main()
