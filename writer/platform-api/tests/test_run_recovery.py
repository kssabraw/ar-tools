"""Unit tests for the startup run-recovery decision (services.orchestrator.
should_resume) — auto-resume orphaned runs, bounded so a run that keeps dying
can't crash-loop the service."""

from services.orchestrator import should_resume


def test_resumes_under_the_cap():
    assert should_resume({"id": "r1", "resume_count": 0}, max_resumes=2)
    assert should_resume({"id": "r1", "resume_count": 1}, max_resumes=2)


def test_fails_at_the_cap():
    assert not should_resume({"id": "r1", "resume_count": 2}, max_resumes=2)
    assert not should_resume({"id": "r1", "resume_count": 5}, max_resumes=2)


def test_missing_resume_count_counts_as_zero():
    # Pre-migration rows have no resume_count; they get their first resume.
    assert should_resume({"id": "r1"}, max_resumes=2)
    assert should_resume({"id": "r1", "resume_count": None}, max_resumes=2)


def test_zero_cap_disables_auto_resume():
    assert not should_resume({"id": "r1", "resume_count": 0}, max_resumes=0)
