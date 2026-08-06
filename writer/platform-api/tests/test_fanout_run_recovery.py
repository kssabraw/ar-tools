"""Recovery of fanout pipeline runs orphaned by a process restart.

Pipeline jobs run in a per-process executor while the session's status carries
the claim, and a SIGKILL never reaches the job's `except` block — so a deploy
mid-run leaves the session `running` with no worker, and `try_claim_run` then
refuses to start a replacement because the session still looks live. On
2026-08-05 that stranded a session one second after its last cluster write,
holding $7.18 of completed expansion hostage behind a progress bar that could
never advance.

These pin the recovery decision and the sweep's failure isolation.
"""

from fanout import run_recovery


# ---- the recovery decision -------------------------------------------------

def test_run_killed_after_expansion_goes_back_to_planning():
    """The valuable case: expansion's keywords are durable, so only the planning
    half was lost and a re-plan costs the planning step alone."""
    status, note = run_recovery.orphan_recovery_target(
        {"id": "s1", "status": "running",
         "statistical_clustering_log": {"topics": {"t1": {"groupings": []}}}}
    )
    assert status == "awaiting_article_planning"
    assert "Expansion had already finished" in note


def test_run_killed_during_expansion_is_recorded_as_an_error():
    """A partial keyword pool isn't resumable — the workspace can only reopen a
    session from awaiting_article_planning or complete — so it says so."""
    status, note = run_recovery.orphan_recovery_target(
        {"id": "s1", "status": "running", "statistical_clustering_log": None}
    )
    assert status == "error"
    assert "start a new session" in note


def test_an_empty_clustering_log_is_not_treated_as_completed_expansion():
    """The log is written with the keywords at the end of the expand job. A row
    carrying an empty shell must not be read as "expansion finished"."""
    for log in ({}, {"topics": {}}, {"topics": None}):
        status, _ = run_recovery.orphan_recovery_target(
            {"id": "s1", "status": "running", "statistical_clustering_log": log}
        )
        assert status == "error"


def test_every_recovery_target_is_a_status_the_user_can_act_on():
    """Neither branch may leave a session in a live status — that's the state
    this whole module exists to get out of."""
    for log in (None, {"topics": {"t1": {}}}):
        status, note = run_recovery.orphan_recovery_target(
            {"id": "s1", "status": "running", "statistical_clustering_log": log}
        )
        assert status not in run_recovery.LIVE_STATUSES
        assert note  # the reason is always recorded


# ---- the sweep -------------------------------------------------------------

class _Store:
    def __init__(self, sessions, fail_on=None):
        self._sessions = sessions
        self._fail_on = fail_on
        self.calls: list[tuple[str, str, str]] = []

    def list_live_sessions(self):
        return self._sessions

    def recover_orphaned_session(self, session_id, status, note):
        if session_id == self._fail_on:
            raise RuntimeError("update failed")
        self.calls.append((session_id, status, note))
        return True


def test_sweep_recovers_each_live_session():
    store = _Store([
        {"id": "s1", "status": "running",
         "statistical_clustering_log": {"topics": {"t": {}}}},
        {"id": "s2", "status": "queued", "statistical_clustering_log": None},
    ])
    assert run_recovery.recover_orphaned_runs(store) == 2
    assert [c[0] for c in store.calls] == ["s1", "s2"]
    assert store.calls[0][1] == "awaiting_article_planning"
    assert store.calls[1][1] == "error"


def test_one_failing_row_does_not_stop_the_others():
    """A DB blip on one session must not strand every other orphan for another
    whole deploy cycle."""
    store = _Store(
        [
            {"id": "bad", "status": "running", "statistical_clustering_log": None},
            {"id": "good", "status": "running", "statistical_clustering_log": None},
        ],
        fail_on="bad",
    )
    assert run_recovery.recover_orphaned_runs(store) == 1
    assert [c[0] for c in store.calls] == ["good"]


def test_sweep_never_raises_when_the_read_fails():
    """It runs in the app lifespan — it must never block startup."""

    class _Broken:
        def list_live_sessions(self):
            raise RuntimeError("supabase down")

    assert run_recovery.recover_orphaned_runs(_Broken()) == 0


def test_nothing_to_do_is_silent():
    store = _Store([])
    assert run_recovery.recover_orphaned_runs(store) == 0
    assert store.calls == []


# Guard: the module must stay importable without the pipeline's heavy dependency
# chain — the storage import is deliberately lazy and injectable so it does.
def test_module_has_no_module_level_store():
    assert run_recovery.LIVE_STATUSES == ("queued", "running")
    assert not hasattr(run_recovery, "store")
