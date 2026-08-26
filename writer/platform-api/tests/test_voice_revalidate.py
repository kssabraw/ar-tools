"""Unit tests for the pure helpers of the voice_revalidate job.

The re-score itself hits nlp and is not unit-tested here; these cover the
applicable-aware per-dimension read and the before/after summary assembly, which
is what the readout depends on.
"""

from __future__ import annotations

from services import voice_revalidate as vr


def test_dim_scores_respects_applicable_and_bool():
    vv = {
        "dimensions": {
            "tone": {"score": 82, "applicable": True},
            "writing_style": {"score": 0, "applicable": False},  # inapplicable -> None
            "person": {"score": True},                           # bool -> None
            "vocabulary": {"score": 71.5, "applicable": True},
            # remaining dimensions absent -> None
        }
    }
    out = vr._dim_scores(vv)
    assert out["tone"] == 82.0
    assert out["writing_style"] is None
    assert out["person"] is None
    assert out["vocabulary"] == 71.5
    assert out["audience_fit"] is None and out["distinctiveness"] is None
    # No scorecard at all -> every dimension None.
    assert vr._dim_scores(None) == {k: None for k in vr.DIMENSIONS}
    assert vr._dim_scores({}) == {k: None for k in vr.DIMENSIONS}


def test_dist_stats_and_bands():
    assert vr._dist([]) is None
    d = vr._dist([70.0, 80.0, 90.0])
    assert d["n"] == 3 and d["min"] == 70.0 and d["max"] == 90.0
    assert d["avg"] == 80.0 and d["median"] == 80.0
    assert d["below_80"] == 1 and d["at_or_above_90"] == 1


def _row(kind, kw, base, new, base_dims=None, new_dims=None, error=None):
    return {
        "kind": kind, "keyword": kw,
        "baseline_score": base, "new_score": new,
        "baseline_dims": base_dims or {k: None for k in vr.DIMENSIONS},
        "new_dims": new_dims or {k: None for k in vr.DIMENSIONS},
        "analysis": "full", "error": error,
    }


def test_summarize_before_after_and_deltas():
    results = [
        _row("local_seo", "a", 84.0, 68.0,
             base_dims={**{k: None for k in vr.DIMENSIONS}, "tone": 88.0},
             new_dims={**{k: None for k in vr.DIMENSIONS}, "tone": 64.0}),
        _row("ecommerce", "b", 82.0, 82.0),
        _row("local_seo", "c", None, None, error="Boom: nope"),  # errored page
    ]
    s = vr._summarize(results)
    assert s["count"] == 3 and s["errors"] == 1
    # Only the two scored pages count toward the distributions.
    assert s["before"]["n"] == 2 and s["after"]["n"] == 2
    assert s["before"]["avg"] == 83.0 and s["after"]["avg"] == 75.0
    assert s["delta"]["down"] == 1 and s["delta"]["unchanged"] == 1 and s["delta"]["up"] == 0
    assert s["delta"]["mean"] == -8.0
    # Per-dimension means average only the pages that scored that dimension.
    assert s["per_dimension"]["tone"] == {"before": 88.0, "after": 64.0}
    assert s["per_dimension"]["vocabulary"] == {"before": None, "after": None}
    # Per-page rows carry the delta and error verbatim.
    assert any(p["error"] and p["baseline"] is None for p in s["pages"])
    assert any(p["delta"] == -16.0 for p in s["pages"])


def test_summarize_empty():
    s = vr._summarize([])
    assert s["count"] == 0 and s["before"] is None and s["after"] is None
