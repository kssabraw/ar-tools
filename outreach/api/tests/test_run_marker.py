"""The job must say which code it is and must never fail silently.

Both behaviours here were bought with real incidents rather than reasoned into existence:

  I-034  a `filter` run died on a missing credential and the deployment reported SUCCESS
  I-052  `verify-reviews` was rejected as an invalid choice by a container holding a merged
         branch's commit — and printed no OUTREACH_RESULT at all, because argparse raises
         SystemExit, which does not derive from Exception

The second is the dangerous one for an unattended cron: a wrong OUTREACH_COMMAND is exactly the
shape a misconfiguration takes, and it was the one failure mode the marker did not cover.
"""

import ast
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


# --- the spend gate ------------------------------------------------------------------------
#
# Bought with an incident like the two above: a `redeploy` replayed a stale config snapshot, ran
# `verify-reviews` with none of its intended flags, and spent ~$0.11 on the 20-lookup default
# nobody asked for. The procedure that was supposed to prevent it (HANDOFF §160/§306: "set
# OUTREACH_COMMAND back to filter afterwards") had been followed. Procedure-safe was not enough,
# so the safe state is now the default and spending requires an affirmative, INTENT-CARRYING
# token.

import os  # noqa: E402

from api.scripts.run_market import (  # noqa: E402
    PAID_COMMANDS,
    resolve_command,
    spend_denial,
)


def test_absent_command_resolves_to_the_free_one():
    assert resolve_command({}) == "filter"
    assert resolve_command({"OUTREACH_COMMAND": ""}) == "filter"
    assert resolve_command({"OUTREACH_COMMAND": "   "}) == "filter"


def test_a_set_command_is_honoured():
    assert resolve_command({"OUTREACH_COMMAND": "verify-reviews"}) == "verify-reviews"
    assert resolve_command({"OUTREACH_COMMAND": " run "}) == "run"


def test_free_commands_need_no_confirmation():
    for command in ("filter", "seed", "probe-dataforseo"):
        assert command not in PAID_COMMANDS
        assert spend_denial(command, {}) is None


def test_the_collector_must_never_be_spend_gated():
    """`tasks_ready` and `task_get` are free; only `task_post` bills. Gating the collector would
    make every cron tick refuse, and the tasks it was supposed to collect would age off the ready
    list — turning a safety measure into the thing that loses the paid work."""
    assert "collect" not in PAID_COMMANDS
    assert spend_denial("collect", {}) is None


def test_scan_tech_is_free_but_the_pixel_spike_is_gated():
    """`scan-tech` fetches prospects' OWN sites over plain HTTP — no paid provider call (PRD §B3),
    same posture as collect. The §16a.1 pixel spike bills an Outscraper enrichment, so it IS gated."""
    assert "scan-tech" not in PAID_COMMANDS
    assert spend_denial("scan-tech", {}) is None
    assert "probe-pixel-field" in PAID_COMMANDS
    assert spend_denial("probe-pixel-field", {}) is not None
    assert spend_denial("probe-pixel-field", {"OUTREACH_CONFIRM_SPEND": "probe-pixel-field"}) is None


def test_every_paid_command_refuses_without_a_token():
    for command in sorted(PAID_COMMANDS):
        denial = spend_denial(command, {})
        assert denial is not None
        assert "OUTREACH_CONFIRM_SPEND" in denial


def test_a_matching_token_authorizes():
    assert spend_denial("run", {"OUTREACH_CONFIRM_SPEND": "run"}) is None
    assert spend_denial("run", {"OUTREACH_CONFIRM_SPEND": " run "}) is None


def test_a_token_for_a_DIFFERENT_command_does_not_authorize():
    """The point of naming the command in the token.

    This is the replayed-snapshot case: a leftover confirmation from a previous intent must not
    approve whatever command happens to be set now.
    """
    denial = spend_denial("run", {"OUTREACH_CONFIRM_SPEND": "verify-reviews"})
    assert denial is not None
    assert "does not authorize" in denial


def test_a_truthy_token_does_not_authorize():
    """`true` is not a command name. A boolean would authorize whatever is set, which is the
    failure mode this replaces rather than reproduces."""
    assert spend_denial("run", {"OUTREACH_CONFIRM_SPEND": "true"}) is not None
    assert spend_denial("run", {"OUTREACH_CONFIRM_SPEND": "1"}) is not None


def test_probe_is_free_until_it_samples():
    """`probe-dataforseo` sends only invalid tasks, which are not billed — until
    --sample-place-id makes it send a real one."""
    assert spend_denial("probe-dataforseo", {}) is None
    assert spend_denial("probe-dataforseo", {}, bills=True) is not None
    assert spend_denial("probe-dataforseo", {"OUTREACH_CONFIRM_SPEND": "probe-dataforseo"}, bills=True) is None


def test_the_ai_granularity_spike_is_gated_despite_costing_almost_nothing():
    """Nine chat completions is well under a cent. It is still gated, because the alternative
    rule — "confirm only if it's expensive" — is a judgement about size, and that judgement is
    made by whoever is wrong about the size."""
    assert "probe-ai-granularity" in PAID_COMMANDS
    assert spend_denial("probe-ai-granularity", {}) is not None
    assert (
        spend_denial("probe-ai-granularity", {"OUTREACH_CONFIRM_SPEND": "probe-ai-granularity"})
        is None
    )


def test_every_command_the_parser_accepts_has_a_handler_and_a_banner_entry():
    """I-052 was a command that existed in one list and not another: `verify-reviews` was
    rejected as an invalid choice by a container that had the code for it. Three lists have to
    agree — argparse choices, the handler dict, and the banner's paid-marking list — and nothing
    but this test makes them."""
    source = (ROOT / "api" / "scripts" / "run_market.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    def string_lists(node) -> list[list[str]]:
        found = []
        for sub in ast.walk(node):
            if isinstance(sub, ast.List) and sub.elts and all(
                isinstance(e, ast.Constant) and isinstance(e.value, str) for e in sub.elts
            ):
                found.append([e.value for e in sub.elts])
        return found

    # The banner list lives in main(); the argparse choices moved into build_parser() when the
    # parser was extracted so the --limit wiring could be tested. Both are still checked — the
    # guarantee is that every list agrees, not that they share a function.
    fns = {
        n.name: n for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name in ("main", "build_parser")
    }
    assert set(fns) == {"main", "build_parser"}, "both command-list owners must exist"
    handler_keys = next(
        {k.value for k in n.keys if isinstance(k, ast.Constant)}
        for n in ast.walk(fns["main"])
        if isinstance(n, ast.Dict) and n.keys
        and all(isinstance(k, ast.Constant) and isinstance(k.value, str) for k in n.keys)
        and "seed" in {k.value for k in n.keys}
    )
    command_lists = [
        set(lst)
        for fn in fns.values()
        for lst in string_lists(fn)
        if "seed" in lst
    ]

    assert len(command_lists) == 2, "expected the banner list and the argparse choices"
    assert command_lists[0] == command_lists[1] == handler_keys
    assert PAID_COMMANDS <= handler_keys


# --- the gate end to end -------------------------------------------------------------------


def _run_clean(argv, extra_env=None):
    """Subprocess with the spend vars stripped, so an ambient token cannot mask a refusal."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("OUTREACH_")}
    env.update(extra_env or {})
    return subprocess.run(
        [sys.executable, "-m", "api.scripts.run_market", *argv],
        cwd=ROOT, capture_output=True, text=True, timeout=60, env=env,
    )


def test_an_unconfirmed_paid_run_refuses_before_it_spends():
    proc = _run_clean(["verify-reviews", "markets/los-angeles-plumbing.json"])
    combined = proc.stdout + proc.stderr

    assert proc.returncode != 0
    assert "OUTREACH_RESULT status=failed" in combined
    assert "OUTREACH_CONFIRM_SPEND" in combined
    # It must refuse at the gate, not inside the handler — a refusal that first opened a provider
    # connection would already have done the thing the gate exists to prevent.
    assert "review verification starting" not in combined


def test_a_stale_token_refuses_the_replayed_command():
    """The incident, reproduced: config says one thing, the leftover confirmation says another."""
    proc = _run_clean(
        ["verify-reviews", "markets/los-angeles-plumbing.json"],
        {"OUTREACH_CONFIRM_SPEND": "filter"},
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode != 0
    assert "does not authorize" in combined


def test_the_banner_shows_the_resolved_command_and_the_token():
    line = build_identity(
        {"OUTREACH_COMMAND": "run", "OUTREACH_CONFIRM_SPEND": "run"}, COMMANDS
    )
    assert "command=run PAID" in line
    assert "confirm=run" in line


def test_the_banner_marks_an_unset_token_and_the_safe_default():
    line = build_identity({}, COMMANDS)
    assert "command=filter" in line
    assert "PAID" not in line
    assert "confirm=(unset)" in line


# --- per-command --limit defaults (the gap that let a silent 20-of-1000 cap ship) --------------


def _parsed(argv):
    """Parse argv exactly as main() does, so these test the REAL wiring rather than a copy."""
    import argparse

    from api.scripts.run_market import build_parser

    return build_parser().parse_args(argv)


def test_limit_flag_has_no_shared_default():
    """REGRESSION: `--limit` defaulted to 20 for EVERY command, so `scan-tech` silently fetched 20
    of ~1,000 sites and still exited 0 — the 'reports clean because it did almost nothing' failure.
    The default now belongs to each command, so omission means that command's own safe value."""
    assert _parsed(["scan-tech", "m.json"]).limit is None


def test_scan_tech_scans_everything_by_default():
    from api.scripts.run_market import scan_tech_limit

    assert scan_tech_limit(_parsed(["scan-tech", "m.json"])) is None      # ALL sites
    assert scan_tech_limit(_parsed(["scan-tech", "m.json", "--limit", "50"])) == 50


def test_paid_spike_defaults_to_a_small_sample():
    from api.scripts.run_market import pixel_probe_limit

    # This one SPENDS, so omission must give the small documented sample, not the old shared 20.
    assert pixel_probe_limit(_parsed(["probe-pixel-field", "m.json"])) == 8
    assert pixel_probe_limit(_parsed(["probe-pixel-field", "m.json", "--limit", "20"])) == 20


def test_unchanged_commands_keep_their_previous_default_of_20():
    from api.scripts.run_market import legacy_limit

    for cmd in ("calibrate", "verify-reviews", "rollup"):
        assert legacy_limit(_parsed([cmd, "m.json"])) == 20
        assert legacy_limit(_parsed([cmd, "m.json", "--limit", "5"])) == 5
