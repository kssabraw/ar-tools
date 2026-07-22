"""DataForSEO Google Maps SERP provider for the geo-grid ranker (Module #5).

The switchover target for Local Dominator (see the switchover plan +
`services/local_dominator.py`). DataForSEO has no native geo-grid endpoint, so
we build the grid ourselves: one `/v3/serp/google/maps/task_post` per in-circle
pin (`location_coordinate = "lat,lng,zoom"`), collected incrementally via
`task_get`. `maps_scan_pins` is the per-pin bookkeeping that makes that
collection idempotent + restart-safe.

Two-phase, identical in shape to the Local Dominator flow so the scheduler /
job worker / cancel paths are unchanged:

  - `start_client_scan_dfs` (from the `maps_scan` job) inserts the `maps_scans`
    row (provider 'dataforseo', status 'polling'), bulk-inserts one
    `maps_scan_pins` row per in-circle pin, and posts the pin tasks. Quick.
  - `poll_scan_dfs` (from the scheduler's `poll_pending_maps_scans` tick) posts
    any not-yet-posted pins, fetches results for posted pins, and — once every
    pin is terminal — assembles per-keyword `maps_scan_results` rows that are
    BYTE-COMPATIBLE with the Local Dominator ones (so every downstream consumer
    is unaffected), then runs the same completion hooks (report + analyzer).

The stored `maps_scan_results` shapes (rank_grid, competitors,
competitors_above, rollups) match `local_dominator` exactly; the tally/order/
exclusion logic in the competitor builders is a faithful port of the LD
builders (`build_competitor_summary` / `build_competitors_above`).
"""

from __future__ import annotations

import asyncio
import base64
import logging
from statistics import mean
from typing import Optional

import httpx

from config import settings
from db.supabase_client import get_supabase
from services import maps_grid

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.dataforseo.com"
_TASK_POST_PATH = "/v3/serp/google/maps/task_post"
_TASK_GET_PATH = "/v3/serp/google/maps/task_get/advanced"
_TIMEOUT = 60.0
_MAX_TASKS_PER_POST = 100  # DataForSEO accepts up to 100 tasks per task_post

# DataForSEO task status codes.
_CODE_OK = 20000            # done, result present
_CODE_TASK_CREATED = 20100  # accepted (task_post) / still creating
_CODE_IN_QUEUE = 40601      # "Task In Queue" — still pending
_CODE_IN_PROGRESS = 40602   # "Task Handed"/in progress — still pending
_PENDING_CODES = {_CODE_TASK_CREATED, _CODE_IN_QUEUE, _CODE_IN_PROGRESS}

# The compact per-pin business record stored in maps_scan_pins.pin_data — a
# list-of-lists (not dicts) to keep 20 items × ~180 pins × keywords small. The
# element order IS the rank order (position 0 = ranks 1st at that pin).
_PIN_FIELDS = (
    "place_id", "name", "rating", "reviews",
    "primary_category", "website", "phone", "lat", "lng",
)


def _auth_header() -> dict[str, str]:
    creds = f"{settings.dataforseo_login}:{settings.dataforseo_password}"
    encoded = base64.b64encode(creds.encode()).decode()
    return {"Authorization": f"Basic {encoded}", "Content-Type": "application/json"}


def _device(config: Optional[dict]) -> str:
    """DataForSEO device (desktop|mobile) from the client's serp_device. 'both'
    collapses to desktop for v1 (no mobile expansion — out of scope)."""
    d = ((config or {}).get("serp_device") or "desktop").lower()
    return "mobile" if d == "mobile" else "desktop"


# ----------------------------------------------------------------------------
# Field extraction — the ONE place raw DataForSEO maps_search field names
# appear (Step 0 fixture confirms these).
# ----------------------------------------------------------------------------
def _item_latlng(item: dict) -> tuple[Optional[float], Optional[float]]:
    """Per-item coordinates. DataForSEO documents top-level `latitude`/
    `longitude` on maps_search items; some payloads nest them under
    `gps_coordinates`. Handle both; (None, None) if absent (directory entries
    then carry null lat/lng — no extra per-competitor lookup, per the plan)."""
    if item.get("latitude") is not None or item.get("longitude") is not None:
        return item.get("latitude"), item.get("longitude")
    gps = item.get("gps_coordinates")
    if isinstance(gps, dict):
        return gps.get("latitude"), gps.get("longitude")
    return None, None


def _business_from_item(item: dict) -> list:
    """A maps_search item → the compact ordered-list record (see _PIN_FIELDS).
    `website` prefers the full `url` when present, else the bare `domain`."""
    rating = item.get("rating") or {}
    lat, lng = _item_latlng(item)
    return [
        item.get("place_id"),
        item.get("title"),
        rating.get("value"),
        rating.get("votes_count"),
        item.get("category"),
        item.get("url") or item.get("domain"),
        item.get("phone"),
        lat,
        lng,
    ]


def _biz(record: list) -> dict:
    """Decode a compact pin_data record back into a named dict."""
    return dict(zip(_PIN_FIELDS, record or []))


# ----------------------------------------------------------------------------
# Pure helpers (no I/O) — independently unit-tested.
# ----------------------------------------------------------------------------
def in_circle(row: int, col: int, n: int) -> bool:
    """The inscribed-circle mask shared with the rollups (same test as the LD
    `summarize_grid`): only pins within the circle are queried / counted."""
    center = (n - 1) / 2
    radius_sq = (n / 2) ** 2
    return (row - center) ** 2 + (col - center) ** 2 <= radius_sq


def incircle_pin_specs(keywords: list[str], points: list, n: int) -> list[dict]:
    """The canonical ordered list of (keyword × in-circle pin) specs — the pin
    rows AND the task bodies are both built from this, in this order, so their
    indices align. `points` are `maps_grid.GridPoint`s."""
    specs: list[dict] = []
    for kw_idx, kw in enumerate(keywords):
        for p in points:
            if in_circle(p.row, p.col, n):
                specs.append({
                    "keyword": kw, "keyword_index": kw_idx,
                    "row_idx": p.row, "col_idx": p.col, "lat": p.lat, "lng": p.lng,
                })
    return specs


def pin_task_body(
    keyword: str, lat: float, lng: float, row: int, col: int,
    zoom: str, depth: int, device: str, scan_id: str = "", kw_idx: Optional[int] = None,
) -> dict:
    """One `task_post` request body for a pin. `tag` is a debug/convenience id
    ("<scan_id>:<kw_idx>:<row>:<col>"); the authoritative task↔pin mapping is the
    `maps_scan_pins` bookkeeping, and posting aligns results by request order."""
    parts = [p for p in ([scan_id] if scan_id else []) + ([str(kw_idx)] if kw_idx is not None else []) + [str(row), str(col)]]
    return {
        "keyword": keyword,
        "location_coordinate": f"{lat},{lng},{zoom}",
        "language_code": settings.dataforseo_default_language_code,
        "device": device,
        "os": "windows",
        "depth": depth,
        "tag": ":".join(parts),
    }


def build_pin_tasks(
    config: dict, keywords: list[str], points: list, zoom: str,
    scan_id: str = "", depth: Optional[int] = None, device: Optional[str] = None,
) -> list[dict]:
    """The `task_post` request bodies for every in-circle pin × keyword."""
    n = max((p.row for p in points), default=-1) + 1
    depth = settings.maps_dfs_depth if depth is None else depth
    device = device or _device(config)
    specs = incircle_pin_specs(keywords, points, n)
    return [
        pin_task_body(s["keyword"], s["lat"], s["lng"], s["row_idx"], s["col_idx"],
                      zoom, depth, device, scan_id, s["keyword_index"])
        for s in specs
    ]


def parse_pin_items(items: list[dict], our_place_id: Optional[str]) -> tuple[Optional[int], list]:
    """From a pin's task_get items: the client's 1-based rank at the pin (None if
    absent from the top-`depth`) + the compact ordered business list for rollups.

    Orders the `maps_search` items by `rank_group` (fallback `rank_absolute`);
    the resulting position IS the rank (position 0 → rank 1)."""
    maps = [it for it in (items or []) if it.get("type") == "maps_search"]
    maps.sort(key=lambda it: (
        (it.get("rank_group") if it.get("rank_group") is not None else it.get("rank_absolute")) is None,
        it.get("rank_group") if it.get("rank_group") is not None else (it.get("rank_absolute") or 0),
    ))
    ordered = [_business_from_item(it) for it in maps]
    client_rank: Optional[int] = None
    if our_place_id:
        for i, rec in enumerate(ordered):
            if rec[0] == our_place_id:  # rec[0] == place_id
                client_rank = i + 1
                break
    return client_rank, ordered


def assemble_rank_grid(pin_rows: list[dict], grid_size: int) -> list[list]:
    """A `grid_size × grid_size` 1-based rank grid (null for unranked AND
    out-of-circle pins) from a keyword's `maps_scan_pins` rows."""
    n = grid_size
    grid: list[list] = [[None] * n for _ in range(n)]
    for pr in pin_rows:
        r, c = pr["row_idx"], pr["col_idx"]
        if 0 <= r < n and 0 <= c < n:
            grid[r][c] = pr.get("client_rank")  # may be None (unranked → null)
    return grid


def summarize_rank_grid(grid: list[list]) -> dict:
    """found/total/top3/top10/average over the in-circle pins of an ALREADY
    1-based grid (the DataForSEO-native analogue of LD's `summarize_grid`)."""
    n = max((len(r) for r in (grid or [])), default=0)
    center = (n - 1) / 2
    radius_sq = (n / 2) ** 2
    ranks: list[int] = []
    total = top3 = top10 = 0
    for ri, row in enumerate(grid or []):
        for ci, cell in enumerate(row):
            if (ri - center) ** 2 + (ci - center) ** 2 > radius_sq:
                continue  # outside the circle — not shown
            total += 1
            if isinstance(cell, (int, float)) and not isinstance(cell, bool) and cell > 0:
                r = int(cell)
                ranks.append(r)
                if r <= 3:
                    top3 += 1
                if r <= 10:
                    top10 += 1
    return {
        "total_pins": total,
        "found_pins": len(ranks),
        "top3_pins": top3,
        "top10_pins": top10,
        "computed_average": round(mean(ranks), 2) if ranks else None,
    }


def build_competitor_summary_dfs(
    pin_rows: list[dict], our_place_id: Optional[str], top_n: int = 25,
) -> list[dict]:
    """Per-keyword competitor leaderboard — the DataForSEO port of
    `local_dominator.build_competitor_summary` (client excluded, §4 target
    shape). Each pin row's `pin_data` is a rank-ordered business list (position
    0 = ranks 1st); tally per business how many pins it appears on / in top-3 /
    top-10 + its average rank, drop the client, and return top_n by local-pack
    presence. All stored pins are in-circle, so no mask is needed here."""
    stats: dict[str, dict] = {}
    meta: dict[str, dict] = {}
    for pr in pin_rows:
        for pos, rec in enumerate(pr.get("pin_data") or []):
            biz = _biz(rec)
            pid = biz.get("place_id")
            if not pid:
                continue
            rank = pos + 1
            s = stats.setdefault(pid, {"found": 0, "top3": 0, "top10": 0, "rank_sum": 0})
            s["found"] += 1
            s["rank_sum"] += rank
            if rank <= 3:
                s["top3"] += 1
            if rank <= 10:
                s["top10"] += 1
            meta.setdefault(pid, biz)

    out: list[dict] = []
    for pid, s in stats.items():
        if our_place_id and pid == our_place_id:
            continue  # exclude the client's own business
        biz = meta[pid]
        out.append({
            "place_id": pid,
            "name": biz.get("name"),
            "rating": biz.get("rating"),
            "reviews": biz.get("reviews"),
            "primary_category": biz.get("primary_category"),
            "website": biz.get("website"),
            "found_pins": s["found"],
            "top3_pins": s["top3"],
            "top10_pins": s["top10"],
            "avg_rank": round(s["rank_sum"] / s["found"], 2) if s["found"] else None,
        })
    out.sort(key=lambda c: (-c["top3_pins"], -c["top10_pins"], -c["found_pins"], c["avg_rank"] or 999))
    return out[:top_n]


def timeout_completes(done: int, total: int) -> bool:
    """On a poll timeout, complete the scan with partial data (missing pins →
    null) when at least 90% of its pins are done; otherwise it's failed."""
    return bool(total) and (done / total) >= 0.9


def next_scan_state(total: int, non_terminal: int, done: int, past_timeout: bool) -> str:
    """Given a scan's pin status counts, the next state of the scan:
    'complete' (every pin terminal), 'timeout_complete' (timed out with ≥90%
    done → keep partial data), 'failed' (timed out below that), or 'polling'.
    Pure — the DB read + finalize/fail side effects live in poll_scan_dfs."""
    if total and non_terminal == 0:
        return "complete"
    if past_timeout:
        return "timeout_complete" if timeout_completes(done, total) else "failed"
    return "polling"


def build_competitors_above_dfs(
    pin_rows: list[dict], grid_size: int, our_place_id: Optional[str],
) -> dict:
    """Per-pin who-outranks-the-client grid — the DataForSEO port of
    `local_dominator.build_competitors_above` (§4 target shape). Per in-circle
    pin, the businesses ranked strictly above the client (client absent from the
    pin's pack → the whole visible pack outranks). Out-of-circle pins → null;
    an in-circle pin that was never fetched (partial/timeout scan → pin_data is
    None) → null too, so the overlay never falsely reads as "client ranks 1st"
    where `rank_grid` shows a hole."""
    n = grid_size
    center = (n - 1) / 2
    radius_sq = (n / 2) ** 2
    by_cell = {(pr["row_idx"], pr["col_idx"]): pr for pr in pin_rows}

    directory: dict[str, dict] = {}
    out_grid: list = []
    for ri in range(n):
        row_out: list = []
        for ci in range(n):
            if (ri - center) ** 2 + (ci - center) ** 2 > radius_sq:
                row_out.append(None)  # outside the circle — not shown
                continue
            pr = by_cell.get((ri, ci))
            if pr is not None and pr.get("pin_data") is None:
                row_out.append(None)  # in-circle pin never fetched → no data (not [])
                continue
            ordered = [_biz(rec) for rec in ((pr.get("pin_data") if pr else None) or [])]
            our_pos = next(
                (p for p, b in enumerate(ordered) if our_place_id and b.get("place_id") == our_place_id),
                None,
            )
            above = ordered[:our_pos] if our_pos is not None else ordered
            pins_above: list = []
            for p, b in enumerate(above):
                pid = b.get("place_id")
                if not pid or (our_place_id and pid == our_place_id):
                    continue
                if pid not in directory:
                    directory[pid] = {
                        "name": b.get("name"),
                        "rating": b.get("rating"),
                        "reviews": b.get("reviews"),
                        "primary_category": b.get("primary_category"),
                        "website": b.get("website"),
                        "lat": b.get("lat"),
                        "lng": b.get("lng"),
                    }
                pins_above.append([pid, p + 1])  # [place_id, 1-based rank]
            row_out.append(pins_above)
        out_grid.append(row_out)
    return {"directory": directory, "grid": out_grid}


# ----------------------------------------------------------------------------
# Fetch (I/O)
# ----------------------------------------------------------------------------
async def post_pin_tasks(bodies: list[dict]) -> list[Optional[str]]:
    """POST pin tasks (batched ≤100/request) to task_post; return task ids
    aligned to `bodies` (None where a task couldn't be created). DataForSEO
    returns tasks in request order; we align by order and cross-check `tag`.
    A whole batch that fails to POST leaves those ids None (rows stay pending,
    the next tick retries)."""
    ids: list[Optional[str]] = [None] * len(bodies)
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for start in range(0, len(bodies), _MAX_TASKS_PER_POST):
            batch = bodies[start:start + _MAX_TASKS_PER_POST]
            try:
                resp = await client.post(f"{_BASE_URL}{_TASK_POST_PATH}", headers=_auth_header(), json=batch)
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                logger.warning("maps_dfs_task_post_failed", extra={"error": str(exc), "batch": len(batch)})
                continue
            for offset, task in enumerate(data.get("tasks") or []):
                # DataForSEO returns tasks in request order, so alignment is by
                # position. We only VERIFY against the echoed tag (a mismatch is
                # logged, not acted on) — reassigning by tag would be unsound
                # because repost tags collide across keywords (no kw index).
                idx = start + offset
                if idx >= len(ids):
                    break  # more tasks echoed than sent (shouldn't happen)
                tag = (task.get("data") or {}).get("tag")
                if tag and offset < len(batch) and batch[offset].get("tag") != tag:
                    logger.warning("maps_dfs_task_order_mismatch",
                                   extra={"expected": batch[offset].get("tag"), "got": tag})
                tid = task.get("id")
                if tid:
                    ids[idx] = tid
    return ids


async def fetch_task_result(task_id: str) -> tuple[str, Optional[list]]:
    """task_get/advanced/{id} → ('done', items) | ('pending', None) |
    ('error', None). Raises on HTTP error (transient — caller leaves the pin
    posted for the next tick)."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(f"{_BASE_URL}{_TASK_GET_PATH}/{task_id}", headers=_auth_header())
    resp.raise_for_status()
    data = resp.json()
    task = (data.get("tasks") or [{}])[0]
    code = task.get("status_code")
    if code == _CODE_OK:
        result = task.get("result")
        if result is not None:
            items = ((result or [{}])[0] or {}).get("items") or []
            return "done", items
        return "pending", None
    if code in _PENDING_CODES:
        return "pending", None
    return "error", None


# ----------------------------------------------------------------------------
# Orchestration (I/O)
# ----------------------------------------------------------------------------
async def start_client_scan_dfs(client_id: str, trigger: str = "scheduled") -> dict:
    """Validate a client's grid config, insert the scan + its in-circle pin
    bookkeeping, and post the pin tasks. Mirrors `local_dominator.start_client_scan`
    but records provider='dataforseo'. Restart-safe: pins are inserted 'pending'
    BEFORE posting, so a crash mid-post just leaves them for the tick to post."""
    supabase = get_supabase()
    config = (
        supabase.table("maps_scan_configs").select("*").eq("client_id", client_id).limit(1).execute()
    ).data
    if not config:
        return {"status": "failed", "error": "no_config"}
    config = config[0]
    if not config.get("google_place_id") or config.get("center_lat") is None or config.get("center_lng") is None:
        return {"status": "failed", "error": "config_incomplete"}

    keywords = [
        k["keyword"]
        for k in (
            supabase.table("maps_keywords").select("keyword")
            .eq("client_id", client_id).eq("active", True).execute()
        ).data or []
    ]
    if not keywords:
        return {"status": "failed", "error": "no_keywords"}

    radius = config["radius_miles"]
    params = maps_grid.grid_params(radius)
    n = params["grid_size"]
    points = maps_grid.generate_grid_points(config["center_lat"], config["center_lng"], radius)

    try:
        scan = supabase.table("maps_scans").insert({
            "client_id": client_id, "provider": "dataforseo", "status": "polling", "trigger": trigger,
            "grid_size": n, "distance": params["distance"], "shape": "square", "radius_miles": radius,
            "center_lat": config["center_lat"], "center_lng": config["center_lng"],
            "resource_category": config.get("resource_category") or "googleMaps",
            "serp_device": config.get("serp_device") or "desktop", "search_terms": keywords,
        }).execute().data[0]
    except Exception as exc:  # nothing created — surface as a failed job, like LD
        logger.warning("maps_dfs_scan_insert_failed", extra={"client_id": client_id, "error": str(exc)})
        return {"status": "failed", "error": str(exc)}
    scan_id = scan["id"]

    specs = incircle_pin_specs(keywords, points, n)
    try:
        supabase.table("maps_scan_pins").insert([
            {"scan_id": scan_id, "keyword": s["keyword"], "row_idx": s["row_idx"],
             "col_idx": s["col_idx"], "lat": s["lat"], "lng": s["lng"]}
            for s in specs
        ]).execute()
    except Exception as exc:  # mark the just-created scan failed rather than orphan it 'polling'
        logger.warning("maps_dfs_pins_insert_failed", extra={"scan_id": scan_id, "error": str(exc)})
        supabase.table("maps_scans").update(
            {"status": "failed", "error": str(exc)[:500]}
        ).eq("id", scan_id).execute()
        return {"status": "failed", "error": str(exc)}

    device = _device(config)
    zoom, depth = settings.maps_dfs_zoom, settings.maps_dfs_depth
    bodies = [
        pin_task_body(s["keyword"], s["lat"], s["lng"], s["row_idx"], s["col_idx"],
                      zoom, depth, device, scan_id, s["keyword_index"])
        for s in specs
    ]
    try:
        tids = await post_pin_tasks(bodies)
    except Exception as exc:  # posting is best-effort; the tick retries pendings
        logger.warning("maps_dfs_post_failed", extra={"client_id": client_id, "error": str(exc)})
        tids = [None] * len(specs)

    posted = [
        {"scan_id": scan_id, "keyword": s["keyword"], "row_idx": s["row_idx"], "col_idx": s["col_idx"],
         "lat": s["lat"], "lng": s["lng"], "task_id": tid, "status": "posted"}
        for s, tid in zip(specs, tids) if tid
    ]
    if posted:
        supabase.table("maps_scan_pins").upsert(posted, on_conflict="scan_id,keyword,row_idx,col_idx").execute()

    logger.info(
        "maps_dfs_scan_started",
        extra={"client_id": client_id, "scan_id": scan_id, "keywords": len(keywords),
               "pins": len(specs), "posted": len(posted)},
    )
    return {"status": "polling", "scan_id": scan_id, "keywords": len(keywords), "pins": len(specs)}


def _uniform_pin_row(pr: dict, **changes) -> dict:
    """A full-keyset maps_scan_pins upsert row (so a batch upsert has uniform
    columns) seeded from the existing pin row, with `changes` applied."""
    row = {
        "scan_id": pr["scan_id"], "keyword": pr["keyword"],
        "row_idx": pr["row_idx"], "col_idx": pr["col_idx"],
        "lat": pr["lat"], "lng": pr["lng"],
        "task_id": pr.get("task_id"), "status": pr.get("status"),
        "attempts": pr.get("attempts") or 0,
        "client_rank": pr.get("client_rank"), "pin_data": pr.get("pin_data"),
        "error": pr.get("error"), "updated_at": "now()",
    }
    row.update(changes)
    return row


async def _handle_posted_pin(pr: dict, our_place_id: Optional[str], zoom: str,
                             depth: int, device: str, scan_id: str) -> Optional[dict]:
    """Fetch one posted pin's result and return the maps_scan_pins upsert row to
    write (None = leave it posted for the next tick). Terminal DataForSEO errors
    are reposted (fresh task) up to `maps_dfs_pin_max_attempts`, then failed."""
    try:
        status, items = await fetch_task_result(pr["task_id"])
    except Exception:
        return None  # transient (429/5xx/network) — leave posted, retry next tick
    if status == "done":
        client_rank, pin_data = parse_pin_items(items, our_place_id)
        return _uniform_pin_row(pr, status="done", client_rank=client_rank, pin_data=pin_data)
    if status == "error":
        attempts = (pr.get("attempts") or 0) + 1
        if attempts < settings.maps_dfs_pin_max_attempts:
            body = pin_task_body(pr["keyword"], pr["lat"], pr["lng"], pr["row_idx"], pr["col_idx"],
                                 zoom, depth, device, scan_id)
            new_tids = await post_pin_tasks([body])
            new_tid = new_tids[0] if new_tids else None
            if new_tid:
                return _uniform_pin_row(pr, status="posted", task_id=new_tid, attempts=attempts)
            return _uniform_pin_row(pr, attempts=attempts)  # keep posted; retry the (old) task
        return _uniform_pin_row(pr, status="failed", attempts=attempts, error="task_error")
    return None  # pending — leave posted


async def poll_scan_dfs(scan_row: dict) -> str:
    """One scheduler tick for one polling DataForSEO scan: post any pending pins,
    fetch posted pins (bounded), and — once every pin is terminal — assemble the
    per-keyword results + run the shared completion hooks. On timeout, complete
    with partial data (missing pins = null) when ≥90% of pins are done, else fail."""
    supabase = get_supabase()
    scan_id = scan_row["id"]
    client_id = scan_row["client_id"]

    cfg = (
        supabase.table("maps_scan_configs").select("google_place_id, serp_device")
        .eq("client_id", client_id).limit(1).execute()
    ).data
    our_place_id = cfg[0].get("google_place_id") if cfg else None
    device = _device(cfg[0] if cfg else {})
    zoom, depth = settings.maps_dfs_zoom, settings.maps_dfs_depth

    batch = (
        supabase.table("maps_scan_pins").select("*")
        .eq("scan_id", scan_id).in_("status", ["pending", "posted"])
        .order("updated_at").limit(settings.maps_dfs_poll_tasks_per_tick).execute()
    ).data or []

    # 1) Post any not-yet-posted pins (start-time posting failures, or restart).
    pending = [p for p in batch if p.get("status") == "pending"]
    if pending:
        bodies = [
            pin_task_body(p["keyword"], p["lat"], p["lng"], p["row_idx"], p["col_idx"],
                          zoom, depth, device, scan_id)
            for p in pending
        ]
        try:
            tids = await post_pin_tasks(bodies)
        except Exception as exc:
            logger.warning("maps_dfs_repost_failed", extra={"scan_id": scan_id, "error": str(exc)})
            tids = [None] * len(pending)
        posted_rows = [
            _uniform_pin_row(p, status="posted", task_id=tid)
            for p, tid in zip(pending, tids) if tid
        ]
        if posted_rows:
            supabase.table("maps_scan_pins").upsert(posted_rows, on_conflict="scan_id,keyword,row_idx,col_idx").execute()

    # 2) Fetch results for posted pins (bounded concurrency on the free task_get).
    posted = [p for p in batch if p.get("status") == "posted" and p.get("task_id")]
    sem = asyncio.Semaphore(settings.maps_dfs_poll_concurrency)

    async def _guarded(pr: dict) -> Optional[dict]:
        async with sem:
            return await _handle_posted_pin(pr, our_place_id, zoom, depth, device, scan_id)

    writes = [w for w in await asyncio.gather(*(_guarded(p) for p in posted)) if w]
    if writes:
        supabase.table("maps_scan_pins").upsert(writes, on_conflict="scan_id,keyword,row_idx,col_idx").execute()

    # 3) Completion check. During bulk collection the tick's batch is capped —
    # more non-terminal pins certainly remain, so the scan can't be complete and
    # we skip the scan-wide status read entirely (only the timeout still matters).
    past_timeout = _past_poll_timeout(scan_row)
    if len(batch) >= settings.maps_dfs_poll_tasks_per_tick and not past_timeout:
        return "polling"

    all_pins = (
        supabase.table("maps_scan_pins").select("status").eq("scan_id", scan_id).execute()
    ).data or []
    total = len(all_pins)
    non_terminal = sum(1 for p in all_pins if p["status"] in ("pending", "posted"))
    done = sum(1 for p in all_pins if p["status"] == "done")
    failed = sum(1 for p in all_pins if p["status"] == "failed")

    state = next_scan_state(total, non_terminal, done, past_timeout)
    if state == "complete":
        return await _finalize_scan(supabase, scan_row, our_place_id, failed)
    if state == "timeout_complete":
        return await _finalize_scan(supabase, scan_row, our_place_id, total - done)
    if state == "failed":
        supabase.table("maps_scans").update(
            {"status": "failed", "error": f"poll_timeout ({done}/{total} pins done)"}
        ).eq("id", scan_id).execute()
        logger.warning("maps_dfs_scan_timeout", extra={"scan_id": scan_id, "done": done, "total": total})
        return "failed"
    return "polling"


async def _finalize_scan(supabase, scan_row: dict, our_place_id: Optional[str],
                         failed_pins: int) -> str:
    """Assemble per-keyword maps_scan_results (byte-compatible with the LD rows),
    mark the scan complete, stamp the config, and run the shared completion hooks
    (report + analyzer). `failed_pins` (unresolved holes) is recorded on the scan."""
    scan_id = scan_row["id"]
    client_id = scan_row["client_id"]
    grid_size = scan_row.get("grid_size") or 0

    pins = (
        supabase.table("maps_scan_pins")
        .select("keyword, row_idx, col_idx, client_rank, pin_data")
        .eq("scan_id", scan_id).execute()
    ).data or []
    by_kw: dict[str, list[dict]] = {}
    for p in pins:
        by_kw.setdefault(p["keyword"], []).append(p)

    inserts: list[dict] = []
    for kw, kw_pins in by_kw.items():
        grid = assemble_rank_grid(kw_pins, grid_size)
        summary = summarize_rank_grid(grid)
        inserts.append({
            "scan_id": scan_id, "client_id": client_id, "keyword": kw,
            "average_rank": summary["computed_average"],
            "found_pins": summary["found_pins"], "total_pins": summary["total_pins"],
            "top3_pins": summary["top3_pins"], "top10_pins": summary["top10_pins"],
            "rank_grid": grid,
            "heatmap_image_url": None, "dynamic_url": None,  # LD-only share artifacts
            "competitors": build_competitor_summary_dfs(kw_pins, our_place_id),
            "competitors_above": build_competitors_above_dfs(kw_pins, grid_size, our_place_id),
        })
    if inserts:
        supabase.table("maps_scan_results").upsert(inserts, on_conflict="scan_id,keyword").execute()

    supabase.table("maps_scans").update({
        "status": "complete", "completed_at": "now()",
        **({"error": f"{failed_pins} pins unresolved"} if failed_pins else {}),
    }).eq("id", scan_id).execute()
    supabase.table("maps_scan_configs").update({"last_scanned_at": "now()"}).eq("client_id", client_id).execute()

    # Shared completion hooks (report + analyzer), skipped for parallel_test scans.
    from services.local_dominator import enqueue_completion_hooks
    enqueue_completion_hooks(scan_id, scan_row.get("trigger"))

    logger.info("maps_dfs_scan_complete",
                extra={"scan_id": scan_id, "keywords": len(inserts), "failed_pins": failed_pins})
    return "complete"


def _past_poll_timeout(scan_row: dict) -> bool:
    """Reuse the LD poll-timeout semantics (age since requested_at/created_at)."""
    from services.local_dominator import _past_poll_timeout as _ld_timeout
    return _ld_timeout(scan_row)
