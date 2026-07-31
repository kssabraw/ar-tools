#!/usr/bin/env python3
"""Standalone calibration pull — stdlib only, no dependencies, no repo needed.

The build sandbox's egress policy blocks Outscraper (ISSUES I-027), so this exists to be run
from anywhere that can reach the API: a laptop, a Railway shell, anywhere.

    export OUTREACH_OUTSCRAPER_API_KEY='...'
    python3 calibrate_standalone.py "plumber, Downtown Los Angeles, CA"

Costs cents. Writes nothing anywhere. Settles three open questions at once:

  * ISSUES I-018 — the real response field names, which could not be verified from the docs.
  * ISSUES I-022 — the real billing rate, by giving you a unit count to divide the dashboard
    charge by.
  * That the client's endpoint, parameters and async polling actually work against the live API.

Paste the output back and the alias map and cost rate get pinned from measurement rather than
assumption.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import Counter

BASE_URLS = [
    "https://api.app.outscraper.com",
    "https://api.app.outscraper.cloud",
    "https://api.outscraper.net",
]

# Mirrors api/services/parser.py FIELD_ALIASES. Kept inline so this file stands alone.
FIELD_ALIASES = {
    "place_id": ("place_id", "google_id", "place_id_google"),
    "name": ("name", "title", "business_name"),
    "category": ("type", "category", "main_category"),
    "address": ("full_address", "address", "formatted_address"),
    "phone": ("phone", "phone_number", "formatted_phone_number"),
    "website": ("site", "website", "url"),
    "rating": ("rating", "average_rating"),
    "review_count": ("reviews", "reviews_count", "review_count", "user_ratings_total"),
    "lat": ("latitude", "lat"),
    "lng": ("longitude", "lng", "lon"),
    "business_status": ("business_status", "status", "permanently_closed"),
}


def call(api_key: str, method: str, path: str, payload: dict | None = None) -> dict:
    body = json.dumps(payload).encode() if payload is not None else None
    last_error = None

    for base in BASE_URLS:
        request = urllib.request.Request(
            f"{base}{path}",
            data=body,
            method=method,
            headers={
                "X-API-KEY": api_key,
                "client": "ar-outreach-calibration",
                **({"Content-Type": "application/json"} if body else {}),
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                parsed = json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            raise SystemExit(f"HTTP {exc.code} from {base}{path}: {exc.read()[:400]!r}")
        except urllib.error.URLError as exc:
            last_error = exc
            print(f"  (host {base} unreachable: {exc.reason}; trying next)", file=sys.stderr)
            continue

        # A 2xx does not mean success — errors come back in the body.
        if parsed.get("error"):
            raise SystemExit(f"Outscraper error: {parsed.get('errorMessage')!r}")
        return parsed

    raise SystemExit(f"all Outscraper hosts unreachable: {last_error}")


def main() -> int:
    api_key = os.environ.get("OUTREACH_OUTSCRAPER_API_KEY", "").strip()
    if not api_key:
        print("set OUTREACH_OUTSCRAPER_API_KEY first", file=sys.stderr)
        return 2

    query = sys.argv[1] if len(sys.argv) > 1 else "plumber, Downtown Los Angeles, CA"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 20

    print(f"submitting {query!r} (limit {limit})")
    submitted = call(
        api_key,
        "POST",
        "/google-maps-search",
        {
            "query": [query],
            "organizationsPerQueryLimit": limit,
            "language": "en",
            "region": "US",
            "async": True,
            "dropDuplicates": False,
            "enrichment": "",  # base tier only — enrichments are billed separately
        },
    )

    request_id = submitted.get("id")
    if not request_id:
        raise SystemExit(f"no request id returned: {submitted!r}")
    print(f"request id: {request_id}\npolling", end="", flush=True)

    deadline = time.monotonic() + 900
    while True:
        archive = call(api_key, "GET", f"/requests/{request_id}")
        if archive.get("status") != "Pending":
            break
        if time.monotonic() > deadline:
            raise SystemExit("still Pending after 15 minutes")
        print(".", end="", flush=True)
        time.sleep(5)

    print(f"\nstatus: {archive.get('status')!r}")
    print("\n--- envelope (everything except `data`) ---")
    print(json.dumps({k: v for k, v in archive.items() if k != "data"}, indent=2)[:2000])

    data = archive.get("data") or []
    places = []
    for entry in data:
        places.extend(entry) if isinstance(entry, list) else places.append(entry)
    places = [p for p in places if isinstance(p, dict)]

    print(f"\n--- {len(places)} places returned ---")
    if not places:
        return 1

    populated = Counter()
    for place in places:
        for key, value in place.items():
            if value not in (None, "", [], {}):
                populated[key] += 1

    claimed = {a for aliases in FIELD_ALIASES.values() for a in aliases}
    print(f"\n--- provider keys ({len(populated)} populated at least once) ---")
    for key, count in sorted(populated.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {'MAPPED  ' if key in claimed else 'unmapped'}  {key:<34} {count}/{len(places)}")

    print("\n--- alias resolution ---")
    for column, aliases in FIELD_ALIASES.items():
        hit = next((a for a in aliases if populated.get(a)), None)
        print(f"  {column:<18} {f'via {hit!r}' if hit else '*** NO ALIAS MATCHED ***'}")

    print("\n--- first place, verbatim ---")
    print(json.dumps(places[0], indent=2)[:4000])

    if "business_status" in populated or "status" in populated:
        key = "business_status" if "business_status" in populated else "status"
        print(f"\n--- {key} values seen: {dict(Counter(str(p.get(key)) for p in places))} ---")

    print(
        f"\nNEXT: check the Outscraper dashboard for what this request cost, then set\n"
        f"  OUTREACH_OUTSCRAPER_COST_PER_1000_PLACES_CENTS = round(cost_cents / {len(places)} * 1000)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
