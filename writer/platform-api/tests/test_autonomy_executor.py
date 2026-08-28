"""Unit tests for the autonomy executor (pure core + a mocked loop pass)."""

from services import autonomy_executor as ax


# --- pure: gather_candidates ------------------------------------------------

def test_gather_candidates_no_behind_goals_is_empty():
    goals = [{"status": "on_track"}, {"status": "achieved"}]
    assert ax.gather_candidates(goals, {"items": [{"kind": "quick_win", "keyword": "x"}]}) == []


def test_gather_candidates_behind_emits_free_rebuild_first():
    out = ax.gather_candidates([{"status": "behind"}], None)
    assert out[0]["action"] == "rebuild_action_plan"
    assert out[0]["cost_usd"] == 0.0 and out[0]["requires"] == "none"


def test_gather_candidates_without_a_city_resolver_are_approval_proposals():
    # "Reoptimize" quick-wins + opportunities want an EXISTING page improved but
    # carry no URL → proposals (reoptimize_page, requires=approval). With no city
    # resolver, a create-page item can't be auto-targeted → also a proposal.
    plan = {"items": [
        {"kind": "quick_win", "keyword": "roof repair", "cta_label": "Reoptimize"},
        {"kind": "opportunity", "keyword": "gutter guards"},
        {"kind": "quick_win", "keyword": "new metal roofs", "cta_label": "Create page"},
        {"kind": "rank_drop", "keyword": "skip me"},        # not content-shaped
        {"kind": "quick_win", "keyword": ""},               # no keyword → skipped
    ]}
    out = ax.gather_candidates([{"status": "overdue"}], plan, resolve_city=None)
    content = [c for c in out if c["action"] != "rebuild_action_plan"]
    assert {c["keyword"] for c in content} == {"roof repair", "gutter guards", "new metal roofs"}
    assert all(c["requires"] == "approval" for c in content)  # nothing auto without a target


def test_gather_candidates_create_page_with_resolvable_keyword_city_is_auto():
    # A create-page keyword whose OWN trailing city resolves → auto, targeting
    # exactly that city. A create-page keyword with no resolvable city (a bare
    # head term) → proposal. A "Reoptimize" quick-win → proposal.
    def fake_resolve(kw):
        if kw == "electrician west palm beach":
            return {"location": "West Palm Beach,Florida,United States", "location_code": 1015}
        return None

    plan = {"items": [
        {"kind": "quick_win", "keyword": "electrician west palm beach", "cta_label": "Create page"},
        {"kind": "quick_win", "keyword": "cybersecurity company", "cta_label": "Create page"},
        {"kind": "quick_win", "keyword": "panel upgrade", "cta_label": "Reoptimize"},
    ]}
    out = ax.gather_candidates([{"status": "behind"}], plan, resolve_city=fake_resolve)

    auto = [c for c in out if c["requires"] == "none" and c["action"] != "rebuild_action_plan"]
    assert len(auto) == 1
    c = auto[0]
    assert c["action"] == "generate_local_seo_page"
    assert c["keyword"] == "electrician west palm beach"
    assert c["location"] == "West Palm Beach,Florida,United States"
    assert c["location_code"] == 1015
    assert c["cost_usd"] == ax.settings.autonomy_local_seo_cost_usd
    # bare head term (no keyword city) → a generate_local_seo_page PROPOSAL
    assert any(c["action"] == "generate_local_seo_page" and c["keyword"] == "cybersecurity company"
               and c["requires"] == "approval" for c in out)
    # the "Reoptimize" one stays a proposal (needs a URL)
    assert any(c["action"] == "reoptimize_page" and c["requires"] == "approval" for c in out)


# --- keyword → city resolution ----------------------------------------------

def _patch_locations(monkeypatch, cities):
    """Fake locations_service.search_locations: returns a city row when the
    query exactly (case-insensitively) equals a known city, else []."""
    from services import locations_service

    async def fake_search(client, query, country=None, limit=10):
        q = query.strip().lower()
        for name, code in cities.items():
            if name.split(",")[0].lower() == q:
                return [{"location_name": name, "location_code": code, "location_type": "City"}]
        return []

    monkeypatch.setattr(locations_service, "search_locations", fake_search)


def test_resolve_keyword_city_uses_longest_trailing_city(monkeypatch):
    _patch_locations(monkeypatch, {"West Palm Beach,Florida,United States": 1015,
                                   "Palm Beach,Florida,United States": 900})
    got = ax._resolve_keyword_city({}, "it support law firm west palm beach")
    # longest trailing window that is a real city wins (not "palm beach")
    assert got == {"location": "West Palm Beach,Florida,United States", "location_code": 1015}


def test_resolve_keyword_city_bare_head_term_is_none(monkeypatch):
    _patch_locations(monkeypatch, {"Miami,Florida,United States": 1013})
    # no trailing city → None (proposal), even though "miami" is a known city…
    assert ax._resolve_keyword_city({}, "cybersecurity company") is None
    # …and a keyword that IS only a city (no leading service word) is not a page
    assert ax._resolve_keyword_city({}, "miami") is None


def test_resolve_keyword_city_trailing_city_resolves(monkeypatch):
    _patch_locations(monkeypatch, {"Miami,Florida,United States": 1013})
    assert ax._resolve_keyword_city({}, "it consulting miami") == {
        "location": "Miami,Florida,United States", "location_code": 1013}


def test_resolve_keyword_city_lookup_failure_is_none(monkeypatch):
    from services import locations_service

    async def boom(*a, **k):
        raise RuntimeError("dataforseo down")

    monkeypatch.setattr(locations_service, "search_locations", boom)
    assert ax._resolve_keyword_city({}, "electrician austin") is None


# --- pure: decide_candidates + AUTO_EXECUTE ---------------------------------

def test_decide_rebuild_autos_content_proposes_at_tier1():
    cands = ax.gather_candidates(
        [{"status": "behind"}],
        {"items": [{"kind": "quick_win", "keyword": "roof repair"}]},
    )
    decided = ax.decide_candidates(
        cands, client_tier=1, budget_left=100.0, freeze=False,
        content_this_week=0, content_cap=3,
    )
    by_action = {d["action"]: d["outcome"] for d in decided}
    assert by_action["rebuild_action_plan"] == "auto"
    assert by_action["reoptimize_page"] == "propose"   # requires=approval (no URL)


def test_freeze_escalates_everything():
    cands = ax.gather_candidates([{"status": "behind"}], None)
    decided = ax.decide_candidates(
        cands, client_tier=2, budget_left=100.0, freeze=True,
        content_this_week=0, content_cap=3,
    )
    assert all(d["outcome"] == "escalate" for d in decided)


def test_auto_execute_allowlist():
    assert ax.AUTO_EXECUTE == frozenset({"rebuild_action_plan", "generate_local_seo_page"})


# --- mocked loop ------------------------------------------------------------

def test_run_autonomy_disabled_short_circuits(monkeypatch):
    monkeypatch.setattr(ax.settings, "autonomy_enabled", False)
    assert ax.run_autonomy_for_client("c1")["status"] == "disabled"


def _loop_setup(monkeypatch, *, budget=500.0, spent=0.0):
    from services import campaign_goals, freeze

    monkeypatch.setattr(ax.settings, "autonomy_enabled", True)
    monkeypatch.setattr(ax.settings, "autonomy_max_tier", 2)
    monkeypatch.setattr(ax.settings, "autonomy_max_content_per_week", 3)
    monkeypatch.setattr(ax.settings, "autonomy_local_seo_cost_usd", 1.0)
    monkeypatch.setattr(
        ax, "_client_row",
        lambda cid: {"id": "c1", "name": "Acme", "autonomy_tier": 2,
                     "retainer_monthly": 3000.0, "is_sab": False,
                     "business_location": "123 Main St, Miami, FL 33101"},
    )
    monkeypatch.setattr(campaign_goals, "assess_goals", lambda cid, today=None: [{"status": "behind"}])
    monkeypatch.setattr(freeze, "is_frozen", lambda cid: False)
    monkeypatch.setattr(
        ax, "_latest_action_plan",
        lambda cid: {"items": [
            {"kind": "quick_win", "keyword": "electrician miami", "cta_label": "Create page"},
            {"kind": "quick_win", "keyword": "panel upgrade", "cta_label": "Reoptimize"},
        ]},
    )
    # inject the keyword→city resolver (never hit DataForSEO in tests): only the
    # keyword whose trailing token is a real city resolves.
    def fake_resolver(client):
        def resolve(kw):
            if kw == "electrician miami":
                return {"location": "Miami,Florida,United States", "location_code": 1013}
            return None
        return resolve
    monkeypatch.setattr(ax, "_keyword_city_resolver", fake_resolver)
    monkeypatch.setattr(ax.autonomy_budget, "budget_for_client", lambda row: budget)
    monkeypatch.setattr(ax.autonomy_budget, "spent_this_month", lambda cid, today=None: spent)
    monkeypatch.setattr(ax.autonomy_budget, "reserve", lambda cid, amt, *, cap, today=None: True)
    monkeypatch.setattr(ax, "_write_ledger", lambda *a, **k: None)
    monkeypatch.setattr(ax, "_emit_digest", lambda *a, **k: None)


def test_run_autonomy_auto_commissions_create_page_proposes_reoptimize(monkeypatch):
    _loop_setup(monkeypatch)
    ran: list[dict] = []
    out = ax.run_autonomy_for_client("c1", execute=lambda cand, cid: ran.append(cand))

    assert out["status"] == "ran" and out["tier"] == 2
    ran_actions = [c["action"] for c in ran]
    # the free rebuild AND the create-page local-SEO page (keyword city resolved)
    assert ran_actions == ["rebuild_action_plan", "generate_local_seo_page"]
    gen = next(c for c in ran if c["action"] == "generate_local_seo_page")
    assert gen["keyword"] == "electrician miami"
    assert gen["location"] == "Miami,Florida,United States" and gen["location_code"] == 1013
    # the "Reoptimize" one (no URL) was proposed, not run
    assert "reoptimize_page" in out["proposed"]
    assert out["cost_usd"] == 1.0   # one local-SEO page reserved


def test_run_autonomy_over_budget_proposes_the_paid_page(monkeypatch):
    # $0 budget: the create-page candidate can't be reserved → proposed, not run.
    _loop_setup(monkeypatch, budget=0.0)
    ran: list[dict] = []
    out = ax.run_autonomy_for_client("c1", execute=lambda cand, cid: ran.append(cand))
    assert [c["action"] for c in ran] == ["rebuild_action_plan"]   # only the free action
    assert "generate_local_seo_page" in out["proposed"]
    assert out["cost_usd"] == 0.0


def test_run_autonomy_not_opted_in_skips(monkeypatch):
    monkeypatch.setattr(ax.settings, "autonomy_enabled", True)
    monkeypatch.setattr(
        ax, "_client_row",
        lambda cid: {"id": "c1", "name": "Acme", "autonomy_tier": 0},
    )
    assert ax.run_autonomy_for_client("c1")["status"] == "not_opted_in"
