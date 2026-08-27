"""Duplicate-artifact guards for work a deploy can interrupt mid-publish.

A requeued job re-runs its handler from the top. Where the handler's side effect
is INTERNAL (a row, a page) that is merely wasteful. Where it is EXTERNAL — a
live Google Business Profile post, a public Google Doc, an article published to
WordPress — the retry creates a second real artifact on a client's property, and
nothing reconciles it afterwards. These pin the guards that stop that.
"""

from __future__ import annotations

from services.gbp_posts_service import match_existing_post


# ── GBP: adopt the post an interrupted attempt already created ───────────────

_LIVE = [
    {"google_name": "accounts/1/locations/2/localPosts/900",
     "summary": "Spring roof tune-up, booked this week.", "topic_type": "standard"},
    {"google_name": "accounts/1/locations/2/localPosts/800",
     "summary": "An older post about gutters.", "topic_type": "standard"},
]


def test_adopts_the_orphan_its_own_attempt_created():
    """The deploy-mid-publish shape: Google made the post, the answer was lost.
    The retry must find it instead of posting a second copy."""
    post = {"summary": "Spring roof tune-up, booked this week.", "topic_type": "standard"}
    found = match_existing_post(post, _LIVE, claimed=set())
    assert found is not None
    assert found["google_name"].endswith("/900")


def test_never_adopts_a_post_another_row_already_owns():
    """A genuine repeat of the same copy must publish for real, not silently
    re-point at the earlier post — that row already recorded this resource."""
    post = {"summary": "Spring roof tune-up, booked this week.", "topic_type": "standard"}
    claimed = {"accounts/1/locations/2/localPosts/900"}
    assert match_existing_post(post, _LIVE, claimed) is None


def test_a_different_summary_is_not_a_match():
    post = {"summary": "Completely different copy.", "topic_type": "standard"}
    assert match_existing_post(post, _LIVE, claimed=set()) is None


def test_same_summary_different_topic_is_not_a_match():
    """topic_type changes the post Google renders, so it isn't the same artifact."""
    post = {"summary": "Spring roof tune-up, booked this week.", "topic_type": "offer"}
    assert match_existing_post(post, _LIVE, claimed=set()) is None


def test_whitespace_differences_still_match():
    """The summary round-trips through Google; incidental whitespace must not
    force a duplicate post."""
    post = {"summary": "  Spring roof tune-up, booked this week.  ", "topic_type": "standard"}
    assert match_existing_post(post, _LIVE, claimed=set()) is not None


def test_an_empty_summary_never_matches():
    """Without content there is nothing to identify the post by — creating is
    safer than adopting an arbitrary one."""
    assert match_existing_post({"summary": "", "topic_type": "standard"}, _LIVE, set()) is None
    assert match_existing_post({"topic_type": "standard"}, _LIVE, set()) is None


def test_no_live_posts_means_create():
    post = {"summary": "Spring roof tune-up, booked this week.", "topic_type": "standard"}
    assert match_existing_post(post, [], claimed=set()) is None


# ── Fanout scheduler: never reap a run this process is still writing ─────────

def test_sweep_skips_runs_this_process_owns(monkeypatch):
    """`_recover_stuck` keys purely on wall-clock age, and a local_seo_page write
    (competitor SERP + generation + 8-engine scoring + auto-reoptimize) can pass
    the stuck cutoff while perfectly healthy. Requeuing it starts a SECOND
    concurrent generation of the same article — double spend, and two trips
    through the auto-publish branch."""
    from fanout.writer import scheduler

    stuck_rows = [
        {"id": "run-live", "status": "running"},
        {"id": "run-abandoned", "status": "running"},
    ]

    class _Res:
        data = stuck_rows

    class _Q:
        def select(self, *_a, **_k): return self
        def eq(self, *_a, **_k): return self
        def lt(self, *_a, **_k): return self
        def execute(self): return _Res()

    class _Client:
        def table(self, _name): return _Q()

    retried: list[str] = []
    monkeypatch.setattr(scheduler, "get_service_client", lambda: _Client())
    monkeypatch.setattr(
        scheduler, "_retry_or_fail",
        lambda row, reason, **kw: retried.append(row["id"]),
    )

    scheduler._own_run("run-live")
    try:
        scheduler._recover_stuck(30)
    finally:
        scheduler._release_run("run-live")

    assert retried == ["run-abandoned"]


def test_ownership_is_released_so_a_later_sweep_can_reap(monkeypatch):
    """The registry must not leak: a run whose worker finished (or died inside
    this process) has to become reapable again."""
    from fanout.writer import scheduler

    scheduler._own_run("r1")
    assert "r1" in scheduler.owned_runs()
    scheduler._release_run("r1")
    assert "r1" not in scheduler.owned_runs()


def test_ownership_snapshot_is_a_copy():
    """Callers iterate it while worker threads mutate the live set."""
    from fanout.writer import scheduler

    scheduler._own_run("r2")
    try:
        snap = scheduler.owned_runs()
        snap.add("not-really-owned")
        assert "not-really-owned" not in scheduler.owned_runs()
    finally:
        scheduler._release_run("r2")
