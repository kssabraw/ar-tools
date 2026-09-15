"""Verify the DataForSEO Google Trends explore endpoint against the LIVE API.

The build sandbox is egress-blocked from api.dataforseo.com (a 403 CONNECT
tunnel), so the Google Trends response shape could NOT be confirmed at build
time. Run this from an environment with egress + the DataForSEO creds (the
Railway PLATFORM service) BEFORE flipping ``google_trends_enabled`` on. It proves,
with a real billed call (~$0.002), the two facts the parser depends on:

  1. ``POST /v3/keywords_data/google_trends/explore/live`` (WITHOUT item_types —
     that documented param is rejected live with task error 40501) returns an
     item of type ``google_trends_queries_list`` carrying ``data.rising`` /
     ``data.top`` arrays of ``{query, value}``. If the shape differs, adjust
     ``google_trends.parse_rising_queries`` to match what this prints.
  2. ``POST /v3/keywords_data/google_trends/categories`` (free) returns the
     category tree ``parse_categories`` flattens.

Run:

    export DATAFORSEO_LOGIN="..." DATAFORSEO_PASSWORD="..."
    python scripts/verify_google_trends.py --keyword "collagen peptides"

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
    ap.add_argument("--login", default=os.environ.get("DATAFORSEO_LOGIN"))
    ap.add_argument("--password", default=os.environ.get("DATAFORSEO_PASSWORD"))
    args = ap.parse_args()

    if not args.login or not args.password:
        print("ERROR: set DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD (or --login/--password).")
        return 2

    headers = _auth(args.login, args.password)

    print(f"== explore/live for {args.keyword!r} (no item_types) ==")
    task = {"keywords": [args.keyword], "type": "web"}
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
                        sample = rows[:3]
                        print(f"    data.{bucket}: {len(rows)} entries; sample={json.dumps(sample)}")
    print(f"  --> google_trends_queries_list present: {found_queries_list}")
    if not found_queries_list:
        print("  !! parser assumption UNMET — inspect the item types above and update parse_rising_queries.")

    print("\n== categories (free) ==")
    try:
        with httpx.Client(timeout=60.0) as client:
            r = client.post(f"{BASE}{CATEGORIES}", headers=headers, json=[{}])
            r.raise_for_status()
            cbody = r.json()
        ctasks = cbody.get("tasks") or []
        first = (ctasks[0].get("result") if ctasks else None)
        print(f"  status_code={cbody.get('status_code')} result_type={type(first).__name__}")
        print(f"  sample={json.dumps(first)[:600] if first else None}")
    except Exception as exc:  # noqa: BLE001
        print(f"  categories call failed: {exc}")

    print("\nDone. If both assumptions held, google_trends_enabled is safe to flip on.")
    return 0 if found_queries_list else 1


if __name__ == "__main__":
    sys.exit(main())
