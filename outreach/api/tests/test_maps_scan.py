"""The geogrid instrument's pure layer.

Two families of test here, and they are not the same kind of claim.

The `task_get` parsing tests assert against an envelope that is PROVEN — the field names come
from `writer/platform-api/services/maps_dataforseo.py`, which has run these two endpoints in
production. Those tests protect a known shape from regression.

The `tasks_ready` tests assert against an envelope nothing in this codebase has ever called. They
cannot prove the shape is right; what they pin down is the BEHAVIOUR ON A SHAPE WE DO NOT
RECOGNISE — raise, rather than return an empty list — because "nothing is ready" and "I could not
read the response" produce the same silence, and the collector's loop termination depends on
telling them apart.
"""

import pytest

from api.services.maps_scan import (
    CODE_IN_QUEUE,
    CODE_OK,
    CODE_TASK_CREATED,
    MapsScanError,
    build_grid_tasks,
    build_tag,
    chunk,
    grid_task_body,
    is_complete,
    parse_grid_result,
    parse_tag,
    parse_task_post,
    parse_tasks_ready,
    task_state,
)

SNAP = "3fa85f64-5717-4562-b3fc-2c963f66afa6"


class _Point:
    def __init__(self, point_seq, lat, lng):
        self.point_seq = point_seq
        self.lat = lat
        self.lng = lng


# --- the tag ------------------------------------------------------------------------------


def test_a_tag_round_trips():
    assert parse_tag(build_tag(SNAP, 42)) == (SNAP, 42)


def test_an_unrecognised_tag_is_not_an_error():
    """The ready list is account-wide, so it carries tasks from other tools on these credentials.
    Somebody else's work is a normal condition, not a failure."""
    assert parse_tag("some-other-tool:whatever") is None
    assert parse_tag("") is None
    assert parse_tag(None) is None


def test_point_zero_is_a_real_point():
    """point_seq is 0-based and 0 is falsy. A truthiness check anywhere in this path would drop
    the grid's first cell and renumber nothing — the loss would be silent."""
    assert parse_tag(build_tag(SNAP, 0)) == (SNAP, 0)


# --- submission ---------------------------------------------------------------------------


def test_the_body_carries_the_coordinate_and_zoom_together():
    """`lat,lng,zoom` is what makes this a geogrid rather than 81 copies of a city-wide query."""
    body = grid_task_body(
        "plumber", 34.05, -118.24, "t", zoom=13, depth=20, language_code="en"
    )
    assert body["location_coordinate"] == "34.05,-118.24,13"
    assert body["keyword"] == "plumber"
    assert body["depth"] == 20


def test_tasks_are_built_in_point_seq_order_from_the_generator():
    points = [_Point(0, 1.0, 2.0), _Point(1, 1.1, 2.0), _Point(2, 1.2, 2.0)]
    tasks = build_grid_tasks(SNAP, "plumber", points, zoom=13, depth=20, language_code="en")
    assert [seq for seq, _ in tasks] == [0, 1, 2]
    assert [parse_tag(b["tag"])[1] for _, b in tasks] == [0, 1, 2]


def test_batches_respect_the_hundred_task_cap():
    batches = chunk(list(range(250)), 100)
    assert [len(b) for b in batches] == [100, 100, 50]


def test_post_response_is_matched_by_tag_not_by_position():
    """The provider's contract does not guarantee response ordering. Our tags are unique, so
    using them removes an assumption rather than merely checking it."""
    sent = [(0, {"tag": build_tag(SNAP, 0)}), (1, {"tag": build_tag(SNAP, 1)})]
    body = {
        "tasks": [
            {"id": "task-for-1", "status_code": CODE_TASK_CREATED,
             "data": {"tag": build_tag(SNAP, 1)}},
            {"id": "task-for-0", "status_code": CODE_TASK_CREATED,
             "data": {"tag": build_tag(SNAP, 0)}},
        ]
    }
    posted = parse_task_post(body, sent)
    assert [(p.point_seq, p.task_id) for p in posted] == [(0, "task-for-0"), (1, "task-for-1")]


def test_a_point_missing_from_the_response_is_reported_not_dropped():
    """It may or may not have been billed. Silence would leave a paid task with no record, which
    is the one failure the whole bookkeeping design exists to prevent."""
    sent = [(0, {"tag": build_tag(SNAP, 0)}), (1, {"tag": build_tag(SNAP, 1)})]
    body = {"tasks": [{"id": "a", "status_code": CODE_TASK_CREATED,
                       "data": {"tag": build_tag(SNAP, 0)}}]}
    posted = parse_task_post(body, sent)
    assert posted[1].task_id is None
    assert posted[1].error


def test_a_task_level_rejection_is_an_error_even_inside_http_200():
    """The request succeeded; the task did not. A rejection can still echo an id, so acceptance
    is its own flag — treating the id as acceptance would mark the row `submitted` and leave the
    collector polling forever for a result that will never exist."""
    sent = [(0, {"tag": build_tag(SNAP, 0)})]
    body = {"tasks": [{"id": "a", "status_code": 40501, "status_message": "Invalid Field",
                       "data": {"tag": build_tag(SNAP, 0)}}]}
    posted = parse_task_post(body, sent)
    assert posted[0].accepted is False
    assert posted[0].task_id == "a"      # kept: the provider's own logs are keyed by it
    assert "40501" in posted[0].error


def test_an_accepted_task_is_flagged_accepted():
    sent = [(0, {"tag": build_tag(SNAP, 0)})]
    body = {"tasks": [{"id": "a", "status_code": CODE_TASK_CREATED,
                       "data": {"tag": build_tag(SNAP, 0)}}]}
    assert parse_task_post(body, sent)[0].accepted is True


def test_a_response_with_no_tasks_array_raises():
    with pytest.raises(MapsScanError):
        parse_task_post({"status_message": "nope"}, [(0, {})])


# --- tasks_ready --------------------------------------------------------------------------


def test_ready_entries_are_split_into_ours_and_everyone_elses():
    body = {
        "tasks": [
            {
                "status_code": CODE_OK,
                "result": [
                    {"id": "ours", "tag": build_tag(SNAP, 7)},
                    {"id": "theirs", "tag": "some-other-system"},
                    {"id": "untagged"},
                ],
            }
        ]
    }
    ready = parse_tasks_ready(body)
    assert [r.task_id for r in ready] == ["ours", "theirs", "untagged"]
    assert ready[0].snapshot_id == SNAP and ready[0].point_seq == 7
    assert ready[1].snapshot_id is None


def test_an_unreadable_ready_response_raises_rather_than_reading_as_empty():
    """The load-bearing one. Returning [] here would end the collector's loop, mark the run
    clean, and leave paid tasks to age off the list — a failure that looks exactly like success."""
    with pytest.raises(MapsScanError):
        parse_tasks_ready({"status_message": "unauthorized"})


def test_a_genuinely_empty_ready_list_is_empty_not_an_error():
    assert parse_tasks_ready({"tasks": [{"status_code": 40102, "result": None}]}) == []


# --- task_get -----------------------------------------------------------------------------


def _done(items):
    return {"tasks": [{"status_code": CODE_OK, "result": [{"items": items}]}]}


def test_rows_carry_place_id_and_rank():
    body = _done([
        {"place_id": "A", "rank_absolute": 1},
        {"place_id": "B", "rank_absolute": 2},
    ])
    state, rows = parse_grid_result(body, point_seq=5)
    assert state == "done"
    assert [(r.place_id, r.rank, r.point_seq) for r in rows] == [("A", 1, 5), ("B", 2, 5)]


def test_an_item_without_a_place_id_is_dropped_not_invented():
    """A grid row joins to a prospect on place_id. A synthesised one matches nothing, forever —
    CLAUDE.md lists fabricating one as an invariant violation."""
    state, rows = parse_grid_result(_done([{"title": "No Id Plumbing"}]), point_seq=1)
    assert state == "done"
    assert rows == []


def test_a_duplicate_listing_keeps_its_best_rank_once():
    body = _done([
        {"place_id": "A", "rank_absolute": 3},
        {"place_id": "A", "rank_absolute": 9},
    ])
    _, rows = parse_grid_result(body, point_seq=1)
    assert [(r.place_id, r.rank) for r in rows] == [("A", 3)]


def test_an_empty_pack_is_a_real_answer_not_a_failure():
    """Some points sit over water or over a stretch with no businesses of that category. 'Nobody
    ranks here' is a finding, and often the strongest one in the grid."""
    state, rows = parse_grid_result(_done([]), point_seq=1)
    assert state == "done"
    assert rows == []


def test_a_queued_task_is_pending():
    body = {"tasks": [{"status_code": CODE_IN_QUEUE}]}
    assert parse_grid_result(body, 1) == ("pending", [])


def test_an_unknown_status_code_is_an_error_not_pending():
    """Pending means 'ask again later'. Guessing pending for a code we do not recognise retries
    forever against a task that will never finish, and the run looks busy rather than broken."""
    assert task_state({"status_code": 40401}) == "error"
    assert task_state({}) == "error"


def test_done_with_no_result_block_is_not_treated_as_an_empty_pack():
    """An envelope we do not understand is a bug; an empty items list is data. Collapsing them
    would record a point as scanned-and-empty on the strength of a response we failed to read."""
    body = {"tasks": [{"status_code": CODE_OK, "result": None}]}
    assert parse_grid_result(body, 1) == ("pending", [])


# --- completeness -------------------------------------------------------------------------


def test_completeness_counts_points_scanned_not_rows_written():
    """A point that returned nothing was still scanned. Counting rows would classify a
    submarket's genuine dead zones as scan failures — the same distinction the rollup's
    completion marker had to be corrected for (I-069)."""
    assert is_complete(81, 81, 0.98) is True
    assert is_complete(80, 81, 0.98) is True     # 0.987
    assert is_complete(79, 81, 0.98) is False    # 0.975


def test_a_zero_denominator_raises_rather_than_dividing():
    with pytest.raises(ValueError):
        is_complete(0, 0, 0.98)
