"""Unit tests for the ecommerce auto-retry loop's plateau stop decision.

Pure + offline — no network, no Anthropic. Covers the disabled default, the
pass-1 no-prior case, gains either side of the threshold, regressions, and the
unscored-pass case the caller's own break owns.
Run with `pytest writer/nlp-api/tests/` or `python -m pytest`.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ecommerce_loop as el  # noqa: E402


# --- min_gain=0 is the shipped default and must never stop -----------------

def test_disabled_by_default_never_stops():
    for prev, cur in [(60.0, 60.0), (60.0, 40.0), (60.0, 90.0), (None, 55.0)]:
        assert el.should_stop_early(prev, cur, 0) is False


def test_negative_min_gain_also_disables():
    assert el.should_stop_early(60.0, 60.0, -1.0) is False


# --- pass 1 has no prior to compare against --------------------------------

def test_no_prior_always_continues():
    assert el.should_stop_early(None, 49.7, 3.0) is False
    assert el.should_stop_early(None, 0.0, 3.0) is False


# --- the gain comparison ---------------------------------------------------

def test_gain_above_threshold_continues():
    assert el.should_stop_early(60.0, 64.0, 3.0) is False


def test_gain_below_threshold_stops():
    assert el.should_stop_early(60.0, 61.5, 3.0) is True


def test_gain_exactly_at_threshold_continues():
    # A pass that delivers exactly the minimum gain has earned another pass —
    # the guard is strictly "less than".
    assert el.should_stop_early(60.0, 63.0, 3.0) is False


def test_zero_gain_stops():
    assert el.should_stop_early(68.3, 68.3, 3.0) is True


def test_regression_stops():
    # A pass that went backwards is a stronger plateau signal than a small
    # gain. Keep-best already protects the output.
    assert el.should_stop_early(71.9, 65.0, 3.0) is True


# --- an unscored pass is the caller's break, not ours ----------------------

def test_unscored_pass_does_not_stop_here():
    assert el.should_stop_early(60.0, None, 3.0) is False
    assert el.should_stop_early(None, None, 3.0) is False


# --- the observed plateau cases from the reference batch -------------------

def test_reference_plateau_cases():
    # Real runs that burned all three passes below the 75 threshold. Each
    # figure is a plausible pass-2→pass-3 movement at a 3.0-point guard.
    assert el.should_stop_early(68.0, 68.8, 3.0) is True    # Tirzepatide
    assert el.should_stop_early(67.9, 68.3, 3.0) is True    # B12
    assert el.should_stop_early(64.0, 71.9, 3.0) is False   # BPC-157 — still climbing
