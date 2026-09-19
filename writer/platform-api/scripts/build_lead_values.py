"""LeadOff — build the exclusive-CPL ``inputs/lead_values.csv`` + the interim
Supabase mirror + the before→after board re-rank comparison (valuation plan v1,
step 1; the plan is ``docs/modules/leadoff-valuation-plan-v1_0.md``).

Runs the pure §4 ladder (``services/leadoff_lead_values.py``) against the current
``market_scanner.lead_values`` rows to produce **exclusive** CPLs with
``source`` + ``confidence``, and:

  * writes ``scripts/leadoff_lead_values.csv`` — the deliverable the owner copies
    to the scanner's ``inputs/lead_values.csv`` (**the source of truth**: a
    ``market_scanner`` reload drops/recreates the table from that CSV, so the two
    new columns ride on it);
  * prints the per-category **before→after mid-CPL comparison** (the re-anchor
    review artifact — plan §11 acceptance #2, emergency trades rise);
  * with ``--upsert``, mirrors the new CPLs into the live table for the interim
    (owner-run, AFTER reviewing the before→after — the plan's "never blind-swap");
  * with ``--board-compare``, recomputes the whole board's grades under the old
    vs new CPLs via ``services/leadoff_export.build_board_rows`` and prints the
    grade-distribution shift + top movers (the deep re-rank view; heavy — reads
    all of ``market_opportunity_master``).

Access: the scoped ``market_scanner`` service-role client (``leadoff_db``), same
as ``export_leadoff_board.py``. Reads can be fed from a JSON dump instead
(``--from-json``) so the CSV can be regenerated with no DB egress.

Usage:
  python scripts/build_lead_values.py                     # write CSV + print before→after
  python scripts/build_lead_values.py --from-json rows.json
  python scripts/build_lead_values.py --upsert            # interim mirror to Supabase (owner-run)
  python scripts/build_lead_values.py --board-compare     # full board re-rank diff (heavy)

The interim mirror updates ``cpl_low/mid/high`` (which the live grade path reads);
``source``/``confidence`` are set best-effort only when those columns exist. To
add them to the live table (optional — they ride on the CSV on the next reload):

  -- run in the Supabase SQL editor (grant-preserving; no drop/recreate):
  ALTER TABLE market_scanner.lead_values ADD COLUMN IF NOT EXISTS source text;
  ALTER TABLE market_scanner.lead_values ADD COLUMN IF NOT EXISTS confidence text;
  GRANT SELECT ON market_scanner.lead_values TO service_role;
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import leadoff_lead_values as llv  # noqa: E402  (pure — safe anywhere)

DEFAULT_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "leadoff_lead_values.csv")
# The raw HomeAdvisor True Cost Guide dataset (713 sub-job rows) — the build input
# for the job-value formula + observed-lead-range rungs. Committed next to this
# script; regenerate/refresh it from the owner's scrape_true_cost_guide.py.
DEFAULT_HOMEADVISOR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "homeadvisor_true_cost_guide_full.csv")
CSV_COLUMNS = ["category_name", "cluster", "cpl_low", "cpl_mid", "cpl_high",
               "source", "confidence"]
# The optional interim DDL (grant-preserving; ride on the CSV on the next reload).
MIRROR_DDL = (
    "ALTER TABLE market_scanner.lead_values ADD COLUMN IF NOT EXISTS source text;\n"
    "ALTER TABLE market_scanner.lead_values ADD COLUMN IF NOT EXISTS confidence text;\n"
    "GRANT SELECT ON market_scanner.lead_values TO service_role;"
)


def _read_existing_rows(from_json: str | None, from_csv: str | None) -> list[dict]:
    if from_json:
        with open(from_json, encoding="utf-8") as fh:
            return json.load(fh)
    if from_csv:
        # Offline regeneration from a prior CSV (e.g. the committed
        # leadoff_lead_values.csv): the ladder re-derives the vertical/inherit rows
        # identically (it ignores the input cpl for those) and reads the input cpl
        # only for still-manual rows, so a round-trip is faithful with no DB egress.
        with open(from_csv, newline="", encoding="utf-8") as fh:
            out = []
            for r in csv.DictReader(fh):
                out.append({
                    "category_name": r.get("category_name"),
                    "cluster": r.get("cluster"),
                    "cpl_low": int(r["cpl_low"]) if (r.get("cpl_low") or "").strip() else None,
                    "cpl_mid": int(r["cpl_mid"]) if (r.get("cpl_mid") or "").strip() else None,
                    "cpl_high": int(r["cpl_high"]) if (r.get("cpl_high") or "").strip() else None,
                })
            return out
    from services.leadoff_db import get_leadoff_client
    return (get_leadoff_client().table("lead_values")
            .select("category_name,cluster,cpl_low,cpl_mid,cpl_high")
            .execute().data or [])


def _read_homeadvisor_rows(path: str | None) -> list[dict]:
    """The raw HomeAdvisor True Cost Guide rows (job value + observed lead range).
    Missing file → [] (the ladder degrades to observed-price-only, no formula)."""
    if not path or not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _write_csv(rows: list[dict], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in CSV_COLUMNS})


def _print_before_after(old_rows: list[dict], new_rows: list[dict]) -> None:
    diff = llv.diff_rows(old_rows, new_rows)
    print("\n=== CPL re-anchor: before → after (mid, board default tier) ===")
    print(f"{'category':38} {'old':>6} {'new':>7} {'x':>6}  source")
    for d in diff:
        mult = f"{d['mult']}x" if d["mult"] is not None else "—"
        print(f"{str(d['category_name'])[:38]:38} {str(d['old_mid'] or '—'):>6} "
              f"{str(d['new_mid'] or '—'):>7} {mult:>6}  {d['source']}")
    tally = llv.summarize(new_rows)
    print("\nconfidence tiers:", ", ".join(f"{k}={v}" for k, v in sorted(tally.items())))
    lifts = [d for d in diff if d["mult"] and d["mult"] > 1]
    print(f"categories lifted: {len(lifts)}/{len(diff)}")


def _upsert(new_rows: list[dict]) -> None:
    """Interim mirror — update cpl_low/mid/high (the columns the live grade path
    reads); set source/confidence best-effort (skipped if the columns aren't in
    the live table yet). Never drops/recreates the table (grant-preserving)."""
    from services.leadoff_db import get_leadoff_client
    c = get_leadoff_client()
    have_meta = True
    try:
        c.table("lead_values").select("source").limit(1).execute()
    except Exception:
        have_meta = False
        print("note: source/confidence columns absent — updating CPLs only.\n"
              "      run MIRROR_DDL (see --help) to add provenance columns.")
    updated = 0
    for r in new_rows:
        payload = {k: r[k] for k in ("cpl_low", "cpl_mid", "cpl_high")}
        if have_meta:
            payload["source"] = r.get("source")
            payload["confidence"] = r.get("confidence")
        (c.table("lead_values").update(payload)
         .eq("category_name", r["category_name"]).execute())
        updated += 1
    print(f"mirrored {updated} lead_values rows to market_scanner (interim).")


def _board_compare(old_rows: list[dict], new_rows: list[dict]) -> None:
    """Recompute the whole board under old vs new CPLs and print the grade shift
    + top movers. Heavy (reads all of market_opportunity_master). Reuses the
    tested pure export math so the diff matches what a re-export would produce."""
    from collections import Counter

    from services import leadoff_export as lx
    from services.leadoff_db import get_leadoff_client
    c = get_leadoff_client()

    def _read_all(make_query, cap: int = 2_000_000) -> list[dict]:
        out: list[dict] = []
        start = 0
        while start < cap:
            page = make_query().range(start, start + 999).execute().data or []
            out.extend(page)
            if len(page) < 1000:
                break
            start += 1000
        return out

    run = (c.table("market_opportunity_master").select("run_id")
           .order("run_id", desc=True).limit(1).execute().data or [{}])[0].get("run_id")
    master = _read_all(lambda: c.table("market_opportunity_master")
                       .select("city_id,category_id,city_name,state_code,population,"
                               "demand_vol,avg_top5_reviews,exact_cat_holders,"
                               "opportunity_score_v3,low_coverage")
                       .eq("run_id", run).eq("supply_measured", True))
    fq = {(int(r["city_id"]), str(r["category_id"])): r
          for r in _read_all(lambda: c.table("field_quality")
                             .select("city_id,category_id,rev_to_win,top5_rating,name_match"))}
    cats = {r["category_id"]: r["category_name"]
            for r in (c.table("categories").select("category_id,category_name")
                      .execute().data or [])}
    old_cpl = {r["category_name"]: r.get("cpl_mid") for r in old_rows}
    new_cpl = {r["category_name"]: r.get("cpl_mid") for r in new_rows}

    old_board = lx.build_board_rows(master, fq, cats, old_cpl, as_of="old")
    new_board = lx.build_board_rows(master, fq, cats, new_cpl, as_of="new")
    print(f"\n=== board re-rank (run {run}, {len(new_board)} rows) ===")
    print("old grades:", dict(Counter(r["grade"] for r in old_board)))
    print("new grades:", dict(Counter(r["grade"] for r in new_board)))
    by_cat_gain: dict[str, list[float]] = {}
    old_ev = {(r["city_id"], r["category_id"]): r["exp_val"] for r in old_board}
    for r in new_board:
        o = old_ev.get((r["city_id"], r["category_id"]))
        if o:
            by_cat_gain.setdefault(r["category"], []).append(r["exp_val"] / o)
    ranked = sorted(((cat, sum(v) / len(v)) for cat, v in by_cat_gain.items()),
                    key=lambda x: -x[1])
    print("\ntop exp_val lifts by category (avg new/old):")
    for cat, m in ranked[:15]:
        print(f"  {cat[:40]:40} {m:.2f}x")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from-json", help="read existing lead_values rows from a JSON dump")
    ap.add_argument("--from-csv",
                    help="read existing rows from a prior CSV (offline regen, no DB)")
    ap.add_argument("--homeadvisor", default=DEFAULT_HOMEADVISOR,
                    help="raw HomeAdvisor True Cost Guide CSV (job-value formula rung)")
    ap.add_argument("--no-homeadvisor", action="store_true",
                    help="skip the HomeAdvisor rungs (observed-price-only ladder)")
    ap.add_argument("--out", default=DEFAULT_OUT, help="CSV output path")
    ap.add_argument("--no-csv", action="store_true", help="skip writing the CSV")
    ap.add_argument("--upsert", action="store_true",
                    help="interim: mirror the new CPLs to market_scanner (owner-run)")
    ap.add_argument("--board-compare", action="store_true",
                    help="recompute the full board old vs new (heavy)")
    args = ap.parse_args()

    old_rows = _read_existing_rows(args.from_json, args.from_csv)
    ha_rows = [] if args.no_homeadvisor else _read_homeadvisor_rows(args.homeadvisor)
    if ha_rows:
        print(f"loaded {len(ha_rows)} HomeAdvisor rows -> job-value formula rung on")
    else:
        print("no HomeAdvisor CSV -> observed-price-only ladder (no formula rung)")
    fc = _formula_config()
    new_rows = llv.build_lead_values(
        old_rows, margin_share=_margin_share(), homeadvisor_rows=ha_rows,
        formula_close_rate=fc["close"], formula_cpl_cap=fc["cap"],
        formula_cpl_floor=fc["floor"])
    if not args.no_csv:
        _write_csv(new_rows, args.out)
        print(f"wrote {len(new_rows)} rows -> {args.out}")
    _print_before_after(old_rows, new_rows)
    if args.board_compare:
        _board_compare(old_rows, new_rows)
    if args.upsert:
        _upsert(new_rows)
    return 0


def _margin_share() -> float:
    try:
        from config import settings
        return float(getattr(settings, "leadoff_cpl_margin_share",
                             llv.DEFAULT_MARGIN_SHARE))
    except Exception:
        return llv.DEFAULT_MARGIN_SHARE


def _formula_config() -> dict:
    """The formula-rung knobs from config (calibratable), defaulting to the pure
    module constants so this runs with no config importable (offline)."""
    try:
        from config import settings
        return {
            "close": float(getattr(settings, "leadoff_formula_close_rate",
                                   llv.FORMULA_CLOSE_RATE)),
            "cap": int(getattr(settings, "leadoff_formula_cpl_cap",
                               llv.FORMULA_CPL_CAP)),
            "floor": int(getattr(settings, "leadoff_formula_cpl_floor",
                                 llv.FORMULA_CPL_FLOOR)),
        }
    except Exception:
        return {"close": llv.FORMULA_CLOSE_RATE, "cap": llv.FORMULA_CPL_CAP,
                "floor": llv.FORMULA_CPL_FLOOR}


if __name__ == "__main__":
    raise SystemExit(main())
