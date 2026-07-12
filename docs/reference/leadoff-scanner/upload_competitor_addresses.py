"""
upload_competitor_addresses -- the ONE-TIME desktop action that gets the
competitor addresses off this machine and into the app (LeadOff proximity,
plan §5c). After this runs, everything downstream — geocoding, clustering,
the board proximity read — is app-side; the desktop never touches proximity
again.

Reads serp_results.csv (the only place the addresses survived) and upserts
the (city_id, category_id, rank_position, business_name, domain,
review_count, address) rows into public.competitor_locations in the suite's
Supabase. Uses SUPABASE_DB_URL (already in the scanner's env). Idempotent —
re-running just re-upserts. ~170k rows, one pass, seconds.

The app's leadoff_geocode job then geocodes them (free Census for the ~88%
with addresses; optional paid Outscraper for the ~12% service-area
businesses). No $137 re-pull.

Usage (scanner project root, env loaded):
  python upload_competitor_addresses.py
"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8")
from pathlib import Path
import pandas as pd
import sqlalchemy
from sqlalchemy import text

DATA = Path.home() / "market-scanner-data" / "intermediate"
SERP_CSV = DATA / "serp_results.csv"
BATCH = 5000


def main():
    url = os.environ.get("SUPABASE_DB_URL")
    if not url:
        sys.exit("SUPABASE_DB_URL not set")
    if not SERP_CSV.exists():
        sys.exit(f"{SERP_CSV} not found")

    df = pd.read_csv(SERP_CSV, dtype={"category_id": str})
    keep = ["city_id", "category_id", "rank_position", "business_name",
            "domain", "review_count", "address"]
    df = df[[c for c in keep if c in df.columns]].copy()
    # blank address -> NULL (service-area businesses); the app fills those via
    # Outscraper only if enabled.
    if "address" in df:
        df["address"] = df["address"].where(df["address"].astype(str).str.strip() != "")
    df = df.dropna(subset=["city_id", "category_id", "rank_position"])
    print(f"rows to upload: {len(df):,} "
          f"({df['address'].notna().sum():,} with an address)")

    eng = sqlalchemy.create_engine(url)
    upsert = text("""
        insert into public.competitor_locations
          (city_id, category_id, rank_position, business_name, domain,
           review_count, address)
        values (:city_id, :category_id, :rank_position, :business_name,
                :domain, :review_count, :address)
        on conflict (city_id, category_id, rank_position) do update set
          business_name = excluded.business_name,
          domain        = excluded.domain,
          review_count  = excluded.review_count,
          address       = excluded.address,
          -- a changed address invalidates the old coordinate
          lat = case when public.competitor_locations.address
                          is distinct from excluded.address
                     then null else public.competitor_locations.lat end,
          lng = case when public.competitor_locations.address
                          is distinct from excluded.address
                     then null else public.competitor_locations.lng end,
          imported_at = now()
    """)
    done = 0
    with eng.begin() as conn:
        for i in range(0, len(df), BATCH):
            chunk = df.iloc[i:i + BATCH]
            conn.execute(upsert, chunk.to_dict("records"))
            done += len(chunk)
            print(f"  upserted {done:,}/{len(df):,}")
    print("done -- addresses are now in the app. "
          "Ask the app chat to run the leadoff_geocode job.")


if __name__ == "__main__":
    main()
