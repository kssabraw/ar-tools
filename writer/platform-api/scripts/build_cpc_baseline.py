"""LeadOff — (re)build public.leadoff_cpc_baseline, the national-median-CPC
denominator for the per-market CPC local modifier on CPL (valuation plan v1
step 2; docs/modules/leadoff-valuation-plan-v1_0.md §3).

Computes the median Google Ads CPC per category from the latest
``market_scanner.market_opportunity_master`` run (its ``category_cpc``) and
upserts it into the app-owned ``public.leadoff_cpc_baseline`` (grant-preserving —
delete-absent + upsert, no drop/recreate). No paid call — pure math over data the
scanner already pulled. Run it after a scanner re-scan/reload so the modifier's
denominator stays current (the modifier degrades to ×1.0 for any category the
baseline is missing, so a stale/empty baseline never breaks a grade).

Usage:
  python scripts/build_cpc_baseline.py --dry-run   # compute + summarize, no writes
  python scripts/build_cpc_baseline.py             # rebuild from the latest run
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import leadoff_cpc  # noqa: E402


def _read_master_and_cats():
    from services.leadoff_db import get_leadoff_client
    c = get_leadoff_client()
    run = (c.table("market_opportunity_master").select("run_id")
           .order("run_id", desc=True).limit(1).execute().data or [{}])[0].get("run_id")
    rows: list[dict] = []
    start = 0
    while True:
        page = (c.table("market_opportunity_master")
                .select("category_id,category_cpc").eq("run_id", run)
                .range(start, start + 999).execute().data or [])
        rows.extend(page)
        if len(page) < 1000:
            break
        start += 1000
    cats = {r["category_id"]: r["category_name"]
            for r in (c.table("categories").select("category_id,category_name")
                      .execute().data or [])}
    return run, rows, cats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="compute + summarize, no writes")
    args = ap.parse_args()

    run, master, cats = _read_master_and_cats()
    baseline = leadoff_cpc.compute_baseline_rows(master, cats)
    print(f"run {run}: {len(master)} master rows -> {len(baseline)} category CPC baselines")
    if baseline:
        cpcs = sorted(r["median_cpc"] for r in baseline)
        print(f"median_cpc range ${cpcs[0]:.2f}–${cpcs[-1]:.2f}")
    if args.dry_run:
        for r in baseline[:12]:
            print(f"  {r['category_name'][:40]:40} ${r['median_cpc']:>7.2f}  (n={r['n']})")
        return 0

    from db.supabase_client import get_supabase
    sb = get_supabase()
    for r in baseline:
        sb.table(leadoff_cpc.BASELINE_TABLE).upsert(
            {**r, "computed_at": "now()"}, on_conflict="category_name").execute()
    print(f"upserted {len(baseline)} rows -> public.{leadoff_cpc.BASELINE_TABLE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
