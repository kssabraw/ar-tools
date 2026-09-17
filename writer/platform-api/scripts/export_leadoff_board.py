"""Rebuild market_scanner.leadoff_board (+ exp_val_percentiles) from the raw scan.

The LeadOff app reads the computed ``leadoff_board`` table; it is an export of
``market_opportunity_master`` (see services/leadoff_export.py for the why + the
math). Run this AFTER the scanner loads a new run to master (e.g. a 15k-30k
population top-up) — otherwise the new tier sits in master and never reaches the
app.

Machine-independent: every input already lives in Supabase, so this runs from
anywhere with the service-role creds (SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY).
It does NOT drop/recreate the table (which would strip the service_role grants) —
it deletes rows and re-inserts, preserving grants.

Usage:
  python scripts/export_leadoff_board.py --dry-run      # compute + summarize, no writes
  python scripts/export_leadoff_board.py                # rebuild from the latest run
  python scripts/export_leadoff_board.py --run 4        # rebuild from a specific run_id
  python scripts/export_leadoff_board.py --as-of 2026-09
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import leadoff_export as lx  # noqa: E402
from services.leadoff_db import get_leadoff_client  # noqa: E402

MASTER = "market_opportunity_master"
MASTER_COLS = ("city_id,category_id,city_name,state_code,population,demand_vol,"
               "avg_top5_reviews,exact_cat_holders,opportunity_score_v3,"
               "low_coverage,last_updated")
_TIER_COL = {"low": "cpl_low", "mid": "cpl_mid", "high": "cpl_high"}
_PAGE = 1000


def _read_all(make_query, page: int = _PAGE, cap: int = 2_000_000) -> list[dict]:
    """Paginate a PostgREST query to completion. ``make_query`` returns a fresh
    ordered query builder each call (so .range() is applied to a clean chain)."""
    out: list[dict] = []
    start = 0
    while True:
        rows = make_query().range(start, start + page - 1).execute().data or []
        out.extend(rows)
        if len(rows) < page:
            return out
        start += page
        if start > cap:
            raise RuntimeError(f"read cap {cap} exceeded — aborting")


def _latest_run(c) -> int:
    rows = (c.table(MASTER).select("run_id").order("run_id", desc=True)
            .limit(1).execute().data or [])
    if not rows:
        sys.exit(f"No rows in {MASTER} — nothing to export.")
    return int(rows[0]["run_id"])


def _write_replace(c, table: str, rows: list[dict], match_filter) -> None:
    """Delete all rows then batch-insert (grant-preserving, no DDL)."""
    match_filter(c.table(table).delete()).execute()
    for i in range(0, len(rows), 500):
        c.table(table).insert(rows[i:i + 500]).execute()


def main() -> None:
    ap = argparse.ArgumentParser(description="Rebuild leadoff_board from market_opportunity_master")
    ap.add_argument("--run", type=int, help="run_id to export (default: latest)")
    ap.add_argument("--as-of", help="vintage label for the board (default: master's YYYY-MM)")
    ap.add_argument("--tier", choices=["low", "mid", "high"], default=lx.DEFAULT_TIER,
                    help="lead-value tier the stored grade uses (default mid)")
    ap.add_argument("--capture", type=float, default=lx.DEFAULT_CAPTURE,
                    help="search->lead capture the stored grade uses (default 0.10)")
    ap.add_argument("--min-rows", type=int, default=1000,
                    help="safety floor: refuse to replace the board with fewer rows")
    ap.add_argument("--dry-run", action="store_true", help="compute + summarize, no writes")
    a = ap.parse_args()

    c = get_leadoff_client()
    run = a.run if a.run is not None else _latest_run(c)
    print(f"Exporting leadoff_board from {MASTER} run_id={run} "
          f"(tier={a.tier}, capture={a.capture})", flush=True)

    # --- read inputs (all already in Supabase) --------------------------------
    master = _read_all(lambda: c.table(MASTER).select(MASTER_COLS)
                       .eq("run_id", run).eq("supply_measured", True)
                       .order("city_id").order("category_id"))
    if not master:
        sys.exit(f"No supply_measured rows for run_id={run}.")
    fq_rows = _read_all(lambda: c.table("field_quality")
                        .select("city_id,category_id,rev_to_win,top5_rating,name_match")
                        .order("city_id").order("category_id"))
    cats = c.table("categories").select("category_id,category_name").execute().data or []
    lv_rows = c.table("lead_values").select(f"category_name,{_TIER_COL[a.tier]}").execute().data or []

    fq = {(int(r["city_id"]), str(r["category_id"])): r for r in fq_rows}
    cat_id_to_name = {r["category_id"]: r["category_name"] for r in cats}
    cat_name_to_cpl = {r["category_name"]: r[_TIER_COL[a.tier]]
                       for r in lv_rows if r.get(_TIER_COL[a.tier]) is not None}

    as_of = a.as_of or _derive_as_of(master)
    print(f"read: {len(master)} measured master rows, {len(fq)} field_quality, "
          f"{len(cat_id_to_name)} categories, {len(cat_name_to_cpl)} lead values; "
          f"as_of={as_of}", flush=True)

    # --- compute (pure) -------------------------------------------------------
    board = lx.build_board_rows(master, fq, cat_id_to_name, cat_name_to_cpl,
                                capture=a.capture, as_of=as_of)
    pct = lx.build_percentiles([r["exp_val"] for r in board])
    dist = Counter(r["grade"] for r in board)
    grade_line = " ".join(f"{g}:{dist.get(g, 0)}" for g in ["A+", "A", "B+", "B", "C", "D", "F"])
    print(f"computed: {len(board)} board rows (thin excluded), {len(pct)} percentiles",
          flush=True)
    print(f"grades: {grade_line}", flush=True)

    if len(board) < a.min_rows:
        sys.exit(f"ABORT: only {len(board)} board rows (< --min-rows {a.min_rows}); "
                 "refusing to replace the live board. Check the run/filters.")

    if a.dry_run:
        for r in board[:3]:
            print(f"  sample: {r['city_name']}, {r['state_code']} · {r['category']} · "
                  f"grade {r['grade']} · exp_val {r['exp_val']} · pop {r['population']}", flush=True)
        print("DRY RUN — no writes.", flush=True)
        return

    # --- write (grant-preserving delete + insert) -----------------------------
    print("writing leadoff_board…", flush=True)
    _write_replace(c, "leadoff_board", board, lambda q: q.gte("city_id", 0))
    print("writing exp_val_percentiles…", flush=True)
    _write_replace(c, "exp_val_percentiles", pct, lambda q: q.gte("pct", 0))
    print(f"DONE: leadoff_board <- {len(board)} rows, exp_val_percentiles <- {len(pct)} rows "
          f"(run_id={run}, as_of={as_of}).", flush=True)


def _derive_as_of(master: list[dict]) -> str:
    """YYYY-MM from the newest master row's last_updated, else this month."""
    stamps = [str(r.get("last_updated") or "") for r in master if r.get("last_updated")]
    if stamps:
        return max(stamps)[:7]
    return _dt.date.today().strftime("%Y-%m")


if __name__ == "__main__":
    main()
