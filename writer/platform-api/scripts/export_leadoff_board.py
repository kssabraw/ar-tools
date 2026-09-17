"""Rebuild market_scanner.leadoff_board (+ exp_val_percentiles) from the raw scan.

The LeadOff app reads the computed ``leadoff_board`` table; it is an export of
``market_opportunity_master`` (see services/leadoff_export.py for the why + the
math). Run this AFTER the scanner loads a new run to master (e.g. a 15k-30k
population top-up) — otherwise the new tier sits in master and never reaches the
app.

Machine-independent: every input already lives in Supabase. Two access paths,
auto-selected (override with --via):
  * ``rest`` — supabase-py (SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY). The
    default when those are set (e.g. the platform-api / ar-tools runtime).
  * ``db``  — a direct Postgres connection (SUPABASE_DB_URL, via SQLAlchemy).
    The default when only SUPABASE_DB_URL is set (e.g. the scanner machine,
    which already has that credential + SQLAlchemy from report.py). This path
    does the replace in a single transaction (atomic — no empty-board window).

Neither path drops/recreates the table (which would strip the service_role
grants) — both delete rows and re-insert, preserving grants.

Usage:
  python scripts/export_leadoff_board.py --dry-run      # compute + summarize, no writes
  python scripts/export_leadoff_board.py                # rebuild from the latest run
  python scripts/export_leadoff_board.py --run 4        # rebuild from a specific run_id
  python scripts/export_leadoff_board.py --via db       # force the SUPABASE_DB_URL path
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import leadoff_export as lx  # noqa: E402  (pure stdlib — safe anywhere)

SCHEMA = "market_scanner"
MASTER = "market_opportunity_master"
MASTER_COLS = ("city_id,category_id,city_name,state_code,population,demand_vol,"
               "avg_top5_reviews,exact_cat_holders,opportunity_score_v3,"
               "low_coverage,last_updated")
FQ_COLS = "city_id,category_id,rev_to_win,top5_rating,name_match"
_TIER_COL = {"low": "cpl_low", "mid": "cpl_mid", "high": "cpl_high"}
_PAGE = 1000


# ── Backends (each imports its own driver lazily) ─────────────────────────────

class RestBackend:
    """supabase-py / PostgREST (SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY)."""

    name = "rest (supabase-py)"

    def __init__(self) -> None:
        from services.leadoff_db import get_leadoff_client
        self.c = get_leadoff_client()

    def _read_all(self, make_query, cap: int = 2_000_000) -> list[dict]:
        out: list[dict] = []
        start = 0
        while True:
            rows = make_query().range(start, start + _PAGE - 1).execute().data or []
            out.extend(rows)
            if len(rows) < _PAGE:
                return out
            start += _PAGE
            if start > cap:
                raise RuntimeError(f"read cap {cap} exceeded — aborting")

    def latest_run(self) -> int:
        rows = (self.c.table(MASTER).select("run_id").order("run_id", desc=True)
                .limit(1).execute().data or [])
        if not rows:
            sys.exit(f"No rows in {MASTER} — nothing to export.")
        return int(rows[0]["run_id"])

    def read_master(self, run: int) -> list[dict]:
        return self._read_all(lambda: self.c.table(MASTER).select(MASTER_COLS)
                              .eq("run_id", run).eq("supply_measured", True)
                              .order("city_id").order("category_id"))

    def read_field_quality(self) -> list[dict]:
        return self._read_all(lambda: self.c.table("field_quality").select(FQ_COLS)
                              .order("city_id").order("category_id"))

    def read_small(self, table: str, cols: str) -> list[dict]:
        return self.c.table(table).select(cols).execute().data or []

    def replace(self, table: str, rows: list[dict], match_col: str) -> None:
        self.c.table(table).delete().gte(match_col, 0).execute()
        for i in range(0, len(rows), 500):
            self.c.table(table).insert(rows[i:i + 500]).execute()


class SqlBackend:
    """Direct Postgres via SQLAlchemy (SUPABASE_DB_URL). Replace is transactional."""

    name = "db (SUPABASE_DB_URL)"

    def __init__(self, db_url: str) -> None:
        import sqlalchemy  # lazy: only the scanner env needs this
        self._sa = sqlalchemy
        self.engine = sqlalchemy.create_engine(db_url)

    def _rows(self, sql: str, **params) -> list[dict]:
        with self.engine.connect() as conn:
            return [dict(r) for r in conn.execute(self._sa.text(sql), params).mappings()]

    def latest_run(self) -> int:
        r = self._rows(f"select max(run_id) as run from {SCHEMA}.{MASTER}")
        if not r or r[0]["run"] is None:
            sys.exit(f"No rows in {MASTER} — nothing to export.")
        return int(r[0]["run"])

    def read_master(self, run: int) -> list[dict]:
        return self._rows(
            f"select {MASTER_COLS} from {SCHEMA}.{MASTER} "
            "where run_id=:run and supply_measured is true", run=run)

    def read_field_quality(self) -> list[dict]:
        return self._rows(f"select {FQ_COLS} from {SCHEMA}.field_quality")

    def read_small(self, table: str, cols: str) -> list[dict]:
        return self._rows(f"select {cols} from {SCHEMA}.{table}")

    def replace(self, table: str, rows: list[dict], match_col: str) -> None:
        # atomic: delete + insert in one transaction (no empty-board window)
        cols = list(rows[0].keys()) if rows else []
        insert = (f"insert into {SCHEMA}.{table} ({', '.join(cols)}) "
                  f"values ({', '.join(':' + c for c in cols)})")
        with self.engine.begin() as conn:
            conn.execute(self._sa.text(f"delete from {SCHEMA}.{table}"))
            for i in range(0, len(rows), 1000):
                conn.execute(self._sa.text(insert), rows[i:i + 1000])


def _select_backend(via: str) -> RestBackend | SqlBackend:
    db_url = os.environ.get("SUPABASE_DB_URL")
    has_rest = bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY"))
    if via == "rest":
        if not has_rest:
            sys.exit("--via rest needs SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY.")
        return RestBackend()
    if via == "db":
        if not db_url:
            sys.exit("--via db needs SUPABASE_DB_URL.")
        return SqlBackend(db_url)
    # auto: prefer REST creds (the app runtime); else the DB URL (the scanner box)
    if has_rest:
        return RestBackend()
    if db_url:
        return SqlBackend(db_url)
    sys.exit("No credentials found. Set SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY, "
             "or SUPABASE_DB_URL.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Rebuild leadoff_board from market_opportunity_master")
    ap.add_argument("--run", type=int, help="run_id to export (default: latest)")
    ap.add_argument("--as-of", help="vintage label for the board (default: master's YYYY-MM)")
    ap.add_argument("--tier", choices=["low", "mid", "high"], default=lx.DEFAULT_TIER,
                    help="lead-value tier the stored grade uses (default mid)")
    ap.add_argument("--capture", type=float, default=lx.DEFAULT_CAPTURE,
                    help="search->lead capture the stored grade uses (default 0.10)")
    ap.add_argument("--via", choices=["auto", "rest", "db"], default="auto",
                    help="data access path (default auto: REST creds, else SUPABASE_DB_URL)")
    ap.add_argument("--min-rows", type=int, default=1000,
                    help="safety floor: refuse to replace the board with fewer rows")
    ap.add_argument("--dry-run", action="store_true", help="compute + summarize, no writes")
    a = ap.parse_args()

    be = _select_backend(a.via)
    run = a.run if a.run is not None else be.latest_run()
    print(f"Exporting leadoff_board from {MASTER} run_id={run} via {be.name} "
          f"(tier={a.tier}, capture={a.capture})", flush=True)

    # --- read inputs ----------------------------------------------------------
    master = be.read_master(run)
    if not master:
        sys.exit(f"No supply_measured rows for run_id={run}.")
    fq_rows = be.read_field_quality()
    cats = be.read_small("categories", "category_id,category_name")
    lv_rows = be.read_small("lead_values", f"category_name,{_TIER_COL[a.tier]}")

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
    be.replace("leadoff_board", board, match_col="city_id")
    print("writing exp_val_percentiles…", flush=True)
    be.replace("exp_val_percentiles", pct, match_col="pct")
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
