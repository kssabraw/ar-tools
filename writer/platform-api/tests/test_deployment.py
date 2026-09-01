"""Unit tests for the /health deployment-identity helper."""

from services import deployment


def test_commit_sha_reads_railway_var(monkeypatch):
    for v in deployment._COMMIT_ENV_VARS:
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "abcdef1234567890")
    assert deployment.commit_sha() == "abcdef1234567890"


def test_commit_sha_priority_and_trims(monkeypatch):
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "  primary  ")
    monkeypatch.setenv("SOURCE_COMMIT", "fallback")
    assert deployment.commit_sha() == "primary"  # first, trimmed


def test_commit_sha_falls_back(monkeypatch):
    monkeypatch.delenv("RAILWAY_GIT_COMMIT_SHA", raising=False)
    monkeypatch.setenv("SOURCE_COMMIT", "fallback-sha")
    assert deployment.commit_sha() == "fallback-sha"


def test_commit_sha_none_when_unset(monkeypatch):
    for v in deployment._COMMIT_ENV_VARS:
        monkeypatch.delenv(v, raising=False)
    assert deployment.commit_sha() is None


def test_deployment_info_shape(monkeypatch):
    for v in deployment._COMMIT_ENV_VARS:
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "0123456789abcdef")
    info = deployment.deployment_info()
    assert info == {"commit": "0123456789abcdef", "commit_short": "0123456"}


def test_deployment_info_none(monkeypatch):
    for v in deployment._COMMIT_ENV_VARS:
        monkeypatch.delenv(v, raising=False)
    assert deployment.deployment_info() == {"commit": None, "commit_short": None}
