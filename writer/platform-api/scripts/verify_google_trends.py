"""Verify the DataForSEO Google Trends endpoints against the LIVE API.

The build sandbox is egress-blocked from api.dataforseo.com (a 403 CONNECT
tunnel), so the Google Trends response shape could NOT be confirmed at build
time. Run this from an environment with egress + the DataForSEO creds (the
Railway PLATFORM service) BEFORE flipping ``google_trends_enabled`` on. It proves,
with real billed calls (~$0.002 each), the facts the parsers depend on:

  1. ``POST /v3/keywords_data/google_trends/explore/live`` WITH
     ``item_types: ["google_trends_queries_list"]`` returns an item of type
     ``google_trends_queries_list`` carrying ``data.rising`` / ``data.top`` arrays
     of ``{query, value}``. Without item_types the default response carries only
     the graph and NO queries list, so the param is required.
  2. ``GET /v3/keywords_data/google_trends/categories`` (free) returns the
     flat category list ``parse_categories`` flattens (a POST 404s).
  3. (``--interest``) the DEFAULT explore response (no item_types) carries a
     ``google_trends_graph`` item whose points are
     ``{date_from, date_to, timestamp, missing_data, values:[int]}`` — the shape
     ``parse_interest_over_time`` reads.

Exits non-zero if any checked assumption is UNMET.

Run:

    export DATAFORSEO_LOGIN="..." DATAFORSEO_PASSWORD="..."
    python scripts/verify_google_trends.py --keyword "collagen peptides"
    python scripts/verify_google_trends.py --keyword "snow blower" --interest

No app imports — standalone on purpose (only ``httpx`` needed), mirroring
scripts/verify_gbp_api_access.py.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys

import httpx

BASE = "https://api.dataforseo.com"
EXPLORE = "/v3/keywords_data/google_trends/explore/live"
CATEGORIES = "/v3/keywords_data/google_trends/categories"


def _auth(login: str, password: str) -> dict:
    tok = base64.b64encode(f"{login}:{password}".encode()).decode()
    return {"Authorization": f"Basic {tok}", "Content-Type": "application/json"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keyword", default="collagen peptides")
    ap.add_argument("--category", type=int, default=None, help="optional category_code filter")
    ap.add_argument("--interest", action="store_true",
                    help="also verify the interest_over_time (graph) slice used by Phase 4")
    ap.add_argument("--login", default=os.environ.get("DATAFORSEO_LOGIN"))
    ap.add_argument("--password", default=os.environ.get("DATAFORSEO_PASSWORD"))
    args = ap.parse_args()

    if not args.login or not args.password:
        print("ERROR: set DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD (or --login/--password).")
        return 2

    headers = _auth(args.login, args.password)
    ok = True

    # --- 1. explore WITH item_types → queries list -------------------------------
    print(f"== explore/live for {args.keyword!r} (item_types=[google_trends_queries_list]) ==")
    task: dict = {"keywords": [args.keyword], "type": "web",
                  "item_types": ["google_trends_queries_list"]}
    if args.category is not None:
        task["category_code"] = args.category
    with httpx.Client(timeout=60.0) as client:
        r = client.post(f"{BASE}{EXPLORE}", headers=headers, json=[task])
        r.raise_for_status()
        body = r.json()

    tasks = body.get("tasks") or []
    status = (tasks[0].get("status_message") if tasks else None)
    print(f"  status_code={body.get('status_code')} task_status={status!r} cost=${body.get('cost')}")
    found_queries_list = False
    for t in tasks:
        for res in t.get("result") or []:
            for item in res.get("items") or []:
                itype = item.get("type")
                print(f"  item.type={itype!r}")
                if itype == "google_trends_queries_list":
                    found_queries_list = True
                    data = item.get("data") or {}
                    for bucket in ("rising", "top"):
                        rows = data.get(bucket) or []
                        print(f"    data.{bucket}: {len(rows)} entries; sample={json.dumps(rows[:3])}")
    print(f"  --> google_trends_queries_list present: {found_queries_list}")
    if not found_queries_list:
        print("  !! UNMET — inspect the item types above and update parse_rising_queries.")
        ok = False

    # --- 2. categories (GET) -----------------------------------------------------
    print("\n== categories (free, GET) ==")
    cats_ok = False
    try:
        with httpx.Client(timeout=60.0) as client:
            r = client.get(f"{BASE}{CATEGORIES}", headers=headers)
            r.raise_for_status()
            cbody = r.json()
        ctasks = cbody.get("tasks") or []
        first = (ctasks[0].get("result") if ctasks else None)
        n = len(first) if isinstance(first, list) else 0
        cats_ok = n > 0
        print(f"  status_code={cbody.get('status_code')} result_type={type(first).__name__} rows={n}")
        print(f"  sample={json.dumps(first[:2]) if isinstance(first, list) else json.dumps(first)[:600]}")
    except Exception as exc:  # noqa: BLE001
        print(f"  categories call failed: {exc}")
    print(f"  --> categories present: {cats_ok}")
    if not cats_ok:
        print("  !! UNMET — categories GET returned no rows; check the endpoint/method.")
        ok = False

    # --- 3. interest_over_time (graph) slice, only with --interest ---------------
    if args.interest:
        print(f"\n== explore/live for {args.keyword!r} (DEFAULT → interest_over_time graph) ==")
        gtask: dict = {"keywords": [args.keyword], "type": "web"}
        if args.category is not None:
            gtask["category_code"] = args.category
        with httpx.Client(timeout=60.0) as client:
            r = client.post(f"{BASE}{EXPLORE}", headers=headers, json=[gtask])
            r.raise_for_status()
            gbody = r.json()
        found_graph = False
        for t in gbody.get("tasks") or []:
            for res in t.get("result") or []:
                for item in res.get("items") or []:
                    if item.get("type") != "google_trends_graph":
                        continue
                    found_graph = True
                    data = item.get("data")
                    points = data if isinstance(data, list) else (
                        (data or {}).get("data") if isinstance(data, dict) else [])
                    points = points or []
                    real = [p for p in points if isinstance(p, dict) and p.get("missing_data") is not True]
                    print(f"    graph points: {len(points)} total, {len(real)} with data; "
                          f"sample={json.dumps(points[:2])}")
        print(f"  --> google_trends_graph present: {found_graph}")
        if not found_graph:
            print("  !! UNMET — no graph item; update parse_interest_over_time.")
            ok = False

    print("\nDone.", "All checked assumptions held — safe to flip google_trends_enabled on."
          if ok else "One or more assumptions UNMET — reconcile the parsers + tests before enabling.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
