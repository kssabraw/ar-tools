"""One deliberately tiny Outscraper pull, to settle three unknowns at once.

    python -m api.scripts.calibrate "plumber, Downtown Los Angeles" --limit 20

  1. ISSUES I-018 — the base response field names, which could not be verified from the docs.
     Prints every key the provider returned, what `parser.FIELD_ALIASES` claimed, and what it
     missed.
  2. ISSUES I-022 — the real billing rate. Compare the reported unit count against the Outscraper
     dashboard and set OUTREACH_OUTSCRAPER_COST_PER_1000_PLACES_CENTS from measurement rather
     than the placeholder.
  3. That the client works end to end against the live API at all.

Touches no database. Costs cents.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from api.config import get_settings  # noqa: E402
from api.services.outscraper_client import (  # noqa: E402
    OutscraperClient,
    TileRequest,
    extract_places,
)
from api.services.parser import FIELD_ALIASES, parse_place, unmapped_fields  # noqa: E402


async def calibrate(query: str, limit: int) -> int:
    settings = get_settings()
    if not settings.outscraper_api_key:
        print("OUTREACH_OUTSCRAPER_API_KEY is not set", file=sys.stderr)
        return 2

    tile = TileRequest(query=query, label="calibration")

    async with OutscraperClient(settings) as client:
        print(f"submitting: {query!r} (limit {limit})")
        request_id = await client.submit_maps_search(tile, limit=limit)
        print(f"request id: {request_id}\npolling…")

        body = await client.fetch_result(request_id)

    print(f"status: {body.get('status')!r}")
    for key in ("id", "status", "data"):
        body.pop(key, None) if key == "_never" else None

    envelope = {k: v for k, v in body.items() if k != "data"}
    print(f"\n--- envelope (everything except `data`) ---\n{json.dumps(envelope, indent=2)[:2000]}")

    places = extract_places(body)
    print(f"\n--- returned {len(places)} places ---")

    if not places:
        print("no places returned — nothing to calibrate against", file=sys.stderr)
        return 1

    # Which keys actually came back, and how often they were populated.
    populated = Counter()
    for place in places:
        for key, value in place.items():
            if value not in (None, "", [], {}):
                populated[key] += 1

    claimed = {alias for aliases in FIELD_ALIASES.values() for alias in aliases}

    print(f"\n--- provider keys ({len(populated)} populated at least once) ---")
    for key, count in sorted(populated.items(), key=lambda kv: (-kv[1], kv[0])):
        mark = "MAPPED  " if key in claimed else "unmapped"
        print(f"  {mark}  {key:<32} populated {count}/{len(places)}")

    print("\n--- alias resolution ---")
    for column, aliases in FIELD_ALIASES.items():
        hit = next((a for a in aliases if populated.get(a)), None)
        status = f"via {hit!r}" if hit else "NO ALIAS MATCHED"
        print(f"  {column:<18} {status}")

    print("\n--- first place, parsed ---")
    first = parse_place(places[0])
    if first is None:
        print("  FAILED TO PARSE — no place_id or no name", file=sys.stderr)
        return 1

    for field_name in (
        "place_id", "name", "category", "address", "phone", "website",
        "rating", "review_count", "lat", "lng", "business_status",
    ):
        print(f"  {field_name:<16} {getattr(first, field_name)!r}")

    print(f"\n  unmapped keys on this place: {unmapped_fields(places[0])}")

    parsed_ok = sum(1 for p in places if parse_place(p) is not None)
    statuses = Counter(str((parse_place(p) or first).business_status) for p in places)
    print(f"\n--- parse rate: {parsed_ok}/{len(places)} ---")
    print(f"--- business_status values: {dict(statuses)} ---")

    print(
        f"\nNEXT: check the Outscraper dashboard for what this request cost. "
        f"{len(places)} places were returned; set "
        f"OUTREACH_OUTSCRAPER_COST_PER_1000_PLACES_CENTS = round(cost_cents / {len(places)} * 1000)."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="One small calibration pull")
    parser.add_argument("query")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    return asyncio.run(calibrate(args.query, args.limit))


if __name__ == "__main__":
    raise SystemExit(main())
