"""The job must say which code it is and must never fail silently.

Both behaviours here were bought with real incidents rather than reasoned into existence:

  I-034  a `filter` run died on a missing credential and the deployment reported SUCCESS
  I-052  `verify-reviews` was rejected as an invalid choice by a container holding a merged
         branch's commit — and printed no OUTREACH_RESULT at all, because argparse raises
         SystemExit, which does not derive from Exception

The second is the dangerous one for an unattended cron: a wrong OUTREACH_COMMAND is exactly the
shape a misconfiguration takes, and it was the one failure mode the marker did not cover.
"""

import subprocess
import sys
from pathlib import Path

from api.scripts.run_market import build_identity

ROOT = Path(__file__).resolve().parents[2]
COMMANDS = ["seed", "ingest", "filter", "run", "calibrate", "verify-reviews"]


# --- build identity ----------------------------------------------------------------------


def test_identity_reports_the_sha_when_the_platform_supplies_one():
    line = build_identity({"RAILWAY_GIT_COMMIT_SHA": "a057279deadbeef"}, COMMANDS)
    assert line.startswith("OUTREACH_BUILD ")
    assert "sha=a057279deadb" in line


def test_identity_prefers_the_baked_sha_over_the_platform_one():
    """The Dockerfile bakes OUTREACH_BUILD_SHA at build time. That is what the IMAGE contains;
    a runtime platform variable describes what the platform *thinks* it deployed, and the two
    disagreeing is precisely the situation worth surfacing."""
    line = build_identity(
        {"OUTREACH_BUILD_SHA": "111111111111aaaa", "RAILWAY_GIT_COMMIT_SHA": "222222222222bbbb"},
        COMMANDS,
    )
    assert "sha=111111111111" in line


def test_identity_degrades_to_unknown_rather_than_crashing():
    """A banner that raised when an env var was missing would take the whole job with it, which
    is a spectacularly bad trade for a diagnostic line."""
    line = build_identity({}, COMMANDS)
    assert "sha=unknown" in line
    assert "branch=unknown" in line


def test_identity_always_carries_the_command_set():
    """The half that works even when the SHA does not. A stale image is self-evident from its
    subcommands — the container that failed I-052 would have shown a list without
    `verify-reviews` on line one, instead of announcing itself by rejecting an argument."""
    line = build_identity({}, COMMANDS)
    assert "verify-reviews" in line
    for cmd in COMMANDS:
        assert cmd in line


# --- the marker covers bad invocations ----------------------------------------------------


def _run(*argv):
    return subprocess.run(
        [sys.executable, "-m", "api.scripts.run_market", *argv],
        cwd=ROOT, capture_output=True, text=True, timeout=60,
    )


def test_an_unknown_command_emits_the_marker_and_exits_non_zero():
    """The I-052 regression, exactly. Before the fix this printed an argparse usage message, exited
    2, and emitted NO marker — so the only signal a monitor could act on was absent for the one
    failure an unattended misconfiguration actually produces."""
    proc = _run("verify-reviewz", "markets/los-angeles-plumbing.json")

    assert proc.returncode != 0
    combined = proc.stdout + proc.stderr
    assert "OUTREACH_RESULT status=failed" in combined
    assert "exit=2" in combined


def test_the_build_banner_precedes_the_failure():
    """Line one, before anything can go wrong — the whole point being that you learn which code
    is running without having to infer it from how it broke."""
    proc = _run("verify-reviewz", "markets/los-angeles-plumbing.json")
    combined = proc.stdout + proc.stderr
    assert "OUTREACH_BUILD " in combined
    assert combined.index("OUTREACH_BUILD ") < combined.index("OUTREACH_RESULT")


def test_help_exits_zero_and_is_not_reported_as_a_failure():
    """`--help` also raises SystemExit. Reporting it as a failed run would train whoever greps
    these markers to ignore them."""
    proc = _run("--help")
    assert proc.returncode == 0
    assert "OUTREACH_RESULT status=failed" not in (proc.stdout + proc.stderr)


def test_a_missing_argument_is_reported_too():
    proc = _run("filter")  # definition is required
    assert proc.returncode != 0
    assert "OUTREACH_RESULT status=failed" in (proc.stdout + proc.stderr)
