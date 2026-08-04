"""The Maps geogrid instrument: request bodies in, grid rows out. No I/O.

PRD §B1. One `task_post` per grid point, the full local pack at each (~20 results), collected
later through `tasks_ready`. Everything in this module is pure so the parts that decide what a
response MEANS can be tested without a provider and without spending anything.

WHAT IS PROVEN HERE AND WHAT IS NOT.

The endpoint and envelope are not guesses. `writer/platform-api/services/maps_dataforseo.py` has
run `/v3/serp/google/maps/task_post` + `/v3/serp/google/maps/task_get/advanced` in production for
the suite's geo-grid, and the field names below (`items[].place_id`, `rank_absolute`,
`rating.votes_count`) come from that working code rather than from documentation. That matters:
this repo has one instrument (`dataforseo_reviews.py`) whose envelope is still unverified
precisely because it was inferred from docs, and the standing decision there is to prove it on a
deliberately small first batch rather than a synthetic test.

`tasks_ready` is the exception — nothing in this codebase has called it. Its parser is therefore
written to be loud about a shape it does not recognise rather than to return an empty list, since
"no tasks are ready" and "I could not read the list" are the same silence and only one of them is
a reason to stop collecting.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

# The two paths, proven in the suite. `advanced` on the GET because the basic result omits
# place_id, which is the join key for everything downstream — a grid row without one matches no
# prospect and can never be scored (CLAUDE.md: never fabricate a place_id).
TASK_POST_PATH = "/v3/serp/google/maps/task_post"
TASK_GET_PATH = "/v3/serp/google/maps/task_get/advanced"
TASKS_READY_PATH = "/v3/serp/google/maps/tasks_ready"

# Provider task-level status codes. These live INSIDE an HTTP 200 — the request succeeded, the
# task did not — which is the single most common way a provider failure gets read as an empty
# result. Named rather than inlined so a status check reads as a claim about the provider.
CODE_OK = 20000             # done, result present
CODE_TASK_CREATED = 20100   # accepted by task_post / still being created
CODE_IN_QUEUE = 40601       # "Task In Queue"
CODE_IN_PROGRESS = 40602    # "Task Handed" / in progress
PENDING_CODES = frozenset({CODE_TASK_CREATED, CODE_IN_QUEUE, CODE_IN_PROGRESS})

# The provider accepts up to 100 tasks per POST (PRD §B1: "MUST batch task submission").
MAX_TASKS_PER_POST = 100


class MapsScanError(RuntimeError):
    """A response this module cannot interpret. Never a silently empty result."""


# --- the tag --------------------------------------------------------------------------------
#
# `<snapshot_id>:<point_seq>`, echoed by the provider on both tasks_ready and task_get. This is
# the recovery key described in the scan_task migration: it is what lets a result be reattached
# when the post's RESPONSE was lost after the provider had already accepted (and billed) the
# request. Keep it parseable and keep it short — the provider caps tags at 255 characters and a
# uuid plus a sequence number is ~40.

_TAG_RE = re.compile(r"^([0-9a-fA-F-]{36}):(\d+)$")


def build_tag(snapshot_id: str, point_seq: int) -> str:
    return f"{snapshot_id}:{point_seq}"


def parse_tag(tag: str | None) -> "tuple[str, int] | None":
    """`(snapshot_id, point_seq)`, or None for anything this system did not send.

    None rather than an exception: the ready list is account-wide, so it will contain tasks from
    other tools sharing these credentials. An unrecognised tag is somebody else's work, which is
    a normal condition and not an error.
    """
    if not tag:
        return None
    match = _TAG_RE.match(tag.strip())
    if not match:
        return None
    return match.group(1), int(match.group(2))


# --- submission -----------------------------------------------------------------------------


def grid_task_body(
    keyword: str,
    lat: float,
    lng: float,
    tag: str,
    *,
    zoom: int,
    depth: int,
    language_code: str,
    device: str = "desktop",
) -> dict[str, Any]:
    """One point's request body.

    `location_coordinate` is `"lat,lng,zoom"` — the zoom is what makes this a geogrid rather than
    a city-wide query, because it sets how tightly the provider simulates being AT that point.
    """
    return {
        "keyword": keyword,
        "location_coordinate": f"{lat},{lng},{zoom}",
        "language_code": language_code,
        "device": device,
        "os": "windows",
        "depth": depth,
        "tag": tag,
    }


def build_grid_tasks(
    snapshot_id: str,
    keyword: str,
    points: Iterable[Any],
    *,
    zoom: int,
    depth: int,
    language_code: str,
    device: str = "desktop",
) -> list[tuple[int, dict[str, Any]]]:
    """`(point_seq, body)` for every point in a snapshot's grid, in point_seq order.

    Takes geometry's `GridPoint`s rather than raw coordinates so the ordering is the generator's
    and not a caller's — point_seq IS the identity of a grid cell, and a caller that enumerated
    its own would eventually disagree with the generator about which cell is which.
    """
    return [
        (
            point.point_seq,
            grid_task_body(
                keyword,
                point.lat,
                point.lng,
                build_tag(snapshot_id, point.point_seq),
                zoom=zoom,
                depth=depth,
                language_code=language_code,
                device=device,
            ),
        )
        for point in points
    ]


def chunk(items: list[Any], size: int = MAX_TASKS_PER_POST) -> list[list[Any]]:
    if size <= 0:
        raise ValueError("size must be positive")
    return [items[i : i + size] for i in range(0, len(items), size)]


@dataclass(frozen=True)
class PostedTask:
    """One point's outcome from a `task_post`.

    `accepted` rather than "did we get an id back", because a REJECTED task can still echo an id.
    Treating a returned id as acceptance would mark the row `submitted` and leave the collector
    polling forever for a result the provider is never going to produce — and the row would look
    like billed work rather than a rejection. The id is kept even when rejected, because it is
    what the provider's own logs are keyed by.
    """

    point_seq: int
    task_id: str | None
    accepted: bool = False
    error: str | None = None


def parse_task_post(body: dict[str, Any], sent: list[tuple[int, dict[str, Any]]]) -> list[PostedTask]:
    """Match a `task_post` response back to the points it was sent for.

    Alignment is BY TAG, not by position. The suite's equivalent aligns positionally and merely
    logs a tag mismatch, which is sound there because its tags are not unique. Ours are, and using
    them removes an assumption about response ordering that nothing in the provider's contract
    actually guarantees.

    A point the response never mentions comes back with `task_id=None` and an error. That is the
    important case and it must not be silent: it is a point we may or may not have been billed
    for, and the caller has to decide, so it is reported rather than dropped.
    """
    tasks = body.get("tasks")
    if not isinstance(tasks, list):
        raise MapsScanError(f"task_post response had no tasks array: {str(body)[:400]}")

    by_seq: dict[int, PostedTask] = {}
    for task in tasks:
        if not isinstance(task, dict):
            continue
        parsed = parse_tag((task.get("data") or {}).get("tag"))
        if parsed is None:
            continue
        _, point_seq = parsed
        code = task.get("status_code")
        task_id = task.get("id")
        if code in (CODE_OK, CODE_TASK_CREATED) and task_id:
            by_seq[point_seq] = PostedTask(
                point_seq=point_seq, task_id=str(task_id), accepted=True
            )
        else:
            by_seq[point_seq] = PostedTask(
                point_seq=point_seq,
                task_id=str(task_id) if task_id else None,
                accepted=False,
                error=f"status_code={code} {task.get('status_message') or ''}".strip(),
            )

    return [
        by_seq.get(
            seq,
            PostedTask(
                point_seq=seq, task_id=None, accepted=False, error="not present in response"
            ),
        )
        for seq, _ in sent
    ]


# --- collection -----------------------------------------------------------------------------


@dataclass(frozen=True)
class ReadyTask:
    task_id: str
    tag: str | None
    snapshot_id: str | None
    point_seq: int | None


def parse_tasks_ready(body: dict[str, Any]) -> list[ReadyTask]:
    """The ready list.

    Raises on a response whose SHAPE is unreadable, and returns an empty list only when the
    provider genuinely reports nothing ready. Those two look identical from the caller's side if
    both return `[]`, and the collector's loop termination depends on telling them apart: an
    unreadable response that reads as "nothing ready" ends the loop, marks the run clean, and
    leaves paid tasks to age off the list.

    Task-level 40102 ("no tasks are ready") is a legitimate empty, not a shape failure.
    """
    tasks = body.get("tasks")
    if not isinstance(tasks, list):
        raise MapsScanError(f"tasks_ready response had no tasks array: {str(body)[:400]}")

    ready: list[ReadyTask] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        result = task.get("result")
        if result is None:
            continue
        for entry in result:
            if not isinstance(entry, dict):
                continue
            task_id = entry.get("id")
            if not task_id:
                continue
            tag = entry.get("tag")
            parsed = parse_tag(tag)
            ready.append(
                ReadyTask(
                    task_id=str(task_id),
                    tag=tag,
                    snapshot_id=parsed[0] if parsed else None,
                    point_seq=parsed[1] if parsed else None,
                )
            )
    return ready


@dataclass(frozen=True)
class GridRow:
    """One business at one point. The full pack is ~20 of these per point."""

    point_seq: int
    place_id: str
    rank: int


def task_state(task: dict[str, Any]) -> str:
    """`done` | `pending` | `error` for one `task_get` task object.

    An unknown code is `error`, not `pending`. Pending means "ask again later", so guessing
    pending for a code we do not recognise would retry forever against a task that will never
    finish, and the run would look busy rather than broken.
    """
    code = task.get("status_code")
    if code == CODE_OK:
        return "done"
    if code in PENDING_CODES:
        return "pending"
    return "error"


def parse_grid_result(body: dict[str, Any], point_seq: int) -> "tuple[str, list[GridRow]]":
    """`(state, rows)` from a `task_get/advanced` response for one point.

    An EMPTY `items` list on a done task is a real answer — some grid points sit over water, or
    over a stretch with no businesses of that category — and it returns `('done', [])`. The
    caller records the point as collected with zero results, which is what keeps a legitimately
    empty cell from reading as a scan failure and dragging down the completeness ratio that
    decides whether the whole snapshot is usable.

    Items without a `place_id` are dropped rather than stored under a synthesised one. A grid row
    joins to a prospect on place_id, so an invented one silently matches nothing forever.
    """
    tasks = body.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise MapsScanError(f"task_get response had no tasks array: {str(body)[:400]}")

    task = tasks[0] if isinstance(tasks[0], dict) else {}
    state = task_state(task)
    if state != "done":
        return state, []

    result = task.get("result")
    if not result:
        # Done with no result block at all. Not an empty pack — an envelope we do not understand,
        # and the difference matters because one is data and the other is a bug.
        return "pending", []

    first = result[0] if isinstance(result[0], dict) else {}
    items = first.get("items") or []

    rows: list[GridRow] = []
    seen: set[str] = set()
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        place_id = item.get("place_id")
        if not place_id:
            continue
        place_id = str(place_id)
        if place_id in seen:
            # The provider occasionally repeats a listing across item types. First occurrence
            # wins: it carries the better (lower) rank, and a duplicate would double-count that
            # business in the coverage denominator.
            continue
        seen.add(place_id)
        rank = item.get("rank_absolute")
        rows.append(
            GridRow(
                point_seq=point_seq,
                place_id=place_id,
                rank=int(rank) if isinstance(rank, int) else index,
            )
        )
    return "done", rows


# --- completeness ---------------------------------------------------------------------------


def completeness(collected_points: int, expected_points: int) -> float:
    if expected_points <= 0:
        raise ValueError("expected_points must be positive")
    return collected_points / expected_points


def is_complete(collected_points: int, expected_points: int, threshold: float) -> bool:
    """PRD §9a.3 — below the threshold a snapshot is marked incomplete and excluded from scoring.

    Counted from POINTS SCANNED, never from grid rows written. A point that returned no
    businesses was scanned; counting rows would classify an honest empty cell as a missing one,
    and a submarket with real dead zones would read as a failed scan every cycle. This is the
    same distinction the rollup's completion marker had to be corrected for (I-069): coverage
    counts what was measured, not what was found.
    """
    return completeness(collected_points, expected_points) >= threshold
