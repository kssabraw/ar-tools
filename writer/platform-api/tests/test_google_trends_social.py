"""Unit tests for services.google_trends_social — the "Trending / social" lane (#1129).

Pure logic only (lexical lean, format hint, social score, lane selection). The
Haiku resolver is I/O and best-effort; the classify_social_fit gate is covered with
the LLM stubbed off.
"""

from services import google_trends_social as gs


# --- lexical_lean (Axis 1, from the text) -------------------------------------
def test_lexical_lean_social_shaped():
    for q in ["cute landscaping vids", "landscaping transformation",
              "oddly satisfying lawn", "landscaping fails", "backyard makeover reveal",
              "landscaping asmr", "lawn care timelapse"]:
        assert gs.lexical_lean(q) == "social", q


def test_lexical_lean_seo_shaped():
    for q in ["what is a landscaper", "landscaping cost per hour",
              "landscapers near me", "how to hire a landscaper",
              "best landscaping company", "landscaping reviews"]:
        assert gs.lexical_lean(q) == "seo", q


def test_lexical_lean_ambiguous_both_or_neither():
    # both a social AND an seo marker → ambiguous (LLM resolves)
    assert gs.lexical_lean("best landscaping transformation vids") == "ambiguous"
    # neither marker → ambiguous
    assert gs.lexical_lean("retatrutide") == "ambiguous"
    assert gs.lexical_lean("") == "ambiguous"
    assert gs.lexical_lean(None) == "ambiguous"


# --- suggested_format ---------------------------------------------------------
def test_suggested_format_maps_markers():
    assert gs.suggested_format("backyard makeover reveal") == "before/after video"
    assert gs.suggested_format("lawn care asmr") == "satisfying / ASMR clip"
    assert gs.suggested_format("landscaping fails compilation") == "meme / short"
    assert gs.suggested_format("cute landscaping vids") == "short-form video"
    assert gs.suggested_format("what is a landscaper") is None  # no format marker


# --- social_score (the lane's sort key) ---------------------------------------
def test_social_score_zero_for_seo_lean():
    assert gs.social_score(300, False, "seo") == 0.0


def test_social_score_monotonic_and_weighted():
    # breakout outranks a high %, which outranks a low %, all social
    low = gs.social_score(100, False, "social")
    high = gs.social_score(2000, False, "social")
    breakout = gs.social_score(0, True, "social")
    assert breakout > high > low > 0
    # an ambiguous row scores below an equivalent social row (lower weight)
    assert gs.social_score(500, False, "social") > gs.social_score(500, False, "ambiguous") > 0


# --- is_social_candidate / select_social_rows (Axis 1 ∧ Axis 2) ---------------
def _row(query, *, qualified=False, lean="social", rising=200.0, breakout=False, score=None):
    r = {"query": query, "qualified": qualified, "social_lean": lean,
         "rising_value": rising, "is_breakout": breakout}
    r["social_score"] = score if score is not None else gs.social_score(rising, breakout, lean)
    return r


def test_is_social_candidate_requires_social_shape_surge_and_no_demand():
    floor = 100.0
    assert gs.is_social_candidate(_row("cute vids", rising=300), floor) is True
    assert gs.is_social_candidate(_row("cute vids", rising=0, breakout=True), floor) is True  # breakout exempt
    # below the velocity floor → out
    assert gs.is_social_candidate(_row("cute vids", rising=40), floor) is False
    # SEO-shaped → out even if surging
    assert gs.is_social_candidate(_row("landscaper cost", lean="seo", rising=900), floor) is False
    # has demand (qualified) → never social lane
    assert gs.is_social_candidate(_row("cute vids", qualified=True, rising=900), floor) is False
    # ambiguous is not the primary lane
    assert gs.is_social_candidate(_row("thing", lean="ambiguous", rising=900), floor) is False


def test_select_social_rows_filters_and_sorts_by_social_score():
    rows = [
        _row("cute landscaping vids", rising=150),
        _row("landscaping asmr", rising=0, breakout=True),   # breakout → top
        _row("what is a landscaper", lean="seo", rising=800),  # dropped
        _row("weak social", rising=20),                       # below floor → dropped
        _row("collagen gummies", qualified=True, rising=900),  # has demand → dropped
    ]
    lane = gs.select_social_rows(rows, 100.0)
    queries = [r["query"] for r in lane]
    assert queries == ["landscaping asmr", "cute landscaping vids"]
    # sorted by social_score desc
    scores = [r["social_score"] for r in lane]
    assert scores == sorted(scores, reverse=True)


# --- apply_lexical (tags unqualified only, leaves qualified untouched) ---------
def test_apply_lexical_tags_only_unqualified():
    rows = [
        {"query": "cute landscaping vids", "qualified": False, "rising_value": 200, "is_breakout": False},
        {"query": "landscaping services", "qualified": True, "rising_value": 100, "is_breakout": False},
    ]
    gs.apply_lexical(rows)
    assert rows[0]["social_lean"] == "social" and rows[0]["suggested_format"] == "short-form video"
    assert rows[0]["social_score"] > 0
    # qualified row is left entirely untouched (no social keys)
    assert "social_lean" not in rows[1]


# --- classify_social_fit gate (LLM stubbed) -----------------------------------
def test_classify_social_fit_disabled_is_noop(monkeypatch):
    monkeypatch.setattr(gs.settings, "google_trends_social_classify_enabled", False)
    rows = [{"query": "cute vids", "qualified": False, "rising_value": 200, "is_breakout": False}]
    gs.classify_social_fit(rows)
    assert "social_lean" not in rows[0]


def test_classify_social_fit_lexical_only_when_llm_off(monkeypatch):
    monkeypatch.setattr(gs.settings, "google_trends_social_classify_enabled", True)
    monkeypatch.setattr(gs.settings, "google_trends_social_llm", False)
    rows = [
        {"query": "cute landscaping vids", "qualified": False, "rising_value": 200, "is_breakout": False},
        {"query": "mystery term", "qualified": False, "rising_value": 300, "is_breakout": False},
    ]
    gs.classify_social_fit(rows)
    assert rows[0]["social_lean"] == "social"
    # ambiguous stays ambiguous with the LLM off (no crash, no key needed)
    assert rows[1]["social_lean"] == "ambiguous"


def test_classify_social_fit_llm_resolves_ambiguous(monkeypatch):
    monkeypatch.setattr(gs.settings, "google_trends_social_classify_enabled", True)
    monkeypatch.setattr(gs, "resolve_ambiguous_with_llm",
                        lambda qs: {"mystery term": {"lean": "social", "format": "short-form video"}})
    rows = [{"query": "mystery term", "qualified": False, "rising_value": 300, "is_breakout": False}]
    gs.classify_social_fit(rows)
    assert rows[0]["social_lean"] == "social"
    assert rows[0]["suggested_format"] == "short-form video"
    assert rows[0]["social_score"] > 0
