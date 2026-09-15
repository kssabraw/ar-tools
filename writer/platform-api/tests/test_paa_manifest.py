"""Pure-helper tests for PAA → SEO Neo Phase 2 (services/paa_manifest.py) — the
prep-sheet manifest core: client-identity extraction, content-row assembly, the
seeded authority/media bundle, rebuild reconciliation, the reused Recipe-Engine
cost rollup, the QA rollup, and the CSV/JSON export rendering. No network / no DB.
"""

from services import paa_manifest as pm


# ── client identity header ────────────────────────────────────────────────────


def test_client_identity_pulls_nap_cid_place_id_gbp_url():
    client = {
        "name": "Acme Roofing",
        "website_url": "https://acme.com",
        "gbp": {
            "business_name": "Acme Roofing LLC",
            "address": "1 Main St, Denver, CO",
            "phone": "+1 303-555-0100",
            "place_id": "ChIJabc123",
            "cid": 987654321,
            "google_maps_uri": "https://maps.google.com/?cid=987654321",
        },
    }
    ident = pm.client_identity(client)
    assert ident["business_name"] == "Acme Roofing LLC"
    assert ident["address"] == "1 Main St, Denver, CO"
    assert ident["phone"] == "+1 303-555-0100"
    assert ident["place_id"] == "ChIJabc123"
    assert ident["cid"] == "987654321"
    assert ident["gbp_url"].endswith("cid=987654321")
    assert ident["website"] == "https://acme.com"


def test_client_identity_falls_back_to_client_name_and_handles_missing():
    ident = pm.client_identity({"name": "Bare Co"})
    assert ident["business_name"] == "Bare Co"
    assert ident["address"] == "" and ident["place_id"] == "" and ident["cid"] == ""
    assert pm.client_identity(None)["business_name"] == ""


# ── category helpers ──────────────────────────────────────────────────────────


def test_is_content_asset_and_qa_rubric():
    assert pm.is_content_asset("paa_post") and pm.is_content_asset("syndication")
    assert not pm.is_content_asset("authority") and not pm.is_content_asset("media")
    # Only page-like content is auto-QA'd.
    assert pm.qa_rubric_for("paa_post") == "blog"
    assert pm.qa_rubric_for("syndication") == "blog"
    assert pm.qa_rubric_for("gbp_post") is None  # JS-heavy Google post page
    assert pm.qa_rubric_for("image") is None


# ── seeded authority + media bundle ───────────────────────────────────────────


def test_seed_authority_rows_are_tracked_only_with_confidence_tags():
    rows = pm.seed_authority_rows(start_position=5)
    kinds = {r["kind"] for r in rows}
    assert {"neo_bucket", "wiki_cloud_stack", "rd_100", "gmbb_blast",
            "rank_your_brand", "press_release"} <= kinds
    for r in rows:
        assert r["category"] == "authority" and r["source"] == "seed"
        assert r["status"] == "planned"          # never executed — human-set
        assert r["confidence_tag"] in ("PROVEN", "THEORY", "BELIEF")
    # RD 100 is deliberately off the Recipe Engine's default menu → no cost type,
    # and its ratio is [THEORY]/disputed.
    rd = next(r for r in rows if r["kind"] == "rd_100")
    assert rd["cost_task_type"] is None and rd["confidence_tag"] == "THEORY"
    # Positions start at the given offset.
    assert rows[0]["position"] == 5


def test_manual_media_rows_never_generated():
    rows = pm.manual_media_rows()
    assert {r["kind"] for r in rows} == {"audio", "video", "influencer"}
    for r in rows:
        assert r["category"] == "media" and r["status"] == "planned"
        assert r["url"] is None  # tracked, not produced by the suite


# ── content-row assembly ──────────────────────────────────────────────────────


def test_build_content_asset_rows_published_pending_and_missing():
    resolved = [
        {"paa_item_id": "i1", "question": "How much does X cost?", "run_id": "r1",
         "published_url": "https://acme.com/x-cost/", "gbp_post_id": "g1",
         "gbp_url": "https://maps.google.com/post1", "syndication": [
             {"label": "Syndication — Google Doc", "url": "https://docs.google.com/d/1"}],
         "image_url": None},
        {"paa_item_id": "i2", "question": "Is X worth it?", "run_id": "r2",
         "published_url": None, "gbp_post_id": None, "gbp_url": None,
         "syndication": [], "image_url": None},
        {"paa_item_id": "i3", "question": "No post yet", "run_id": None,
         "published_url": None, "syndication": []},
    ]
    rows = pm.build_content_asset_rows(resolved)
    by_item = {}
    for r in rows:
        by_item.setdefault(r["paa_item_id"], []).append(r)

    # i1: a collected PAA post + a GBP post + a syndication copy.
    cats1 = [r["category"] for r in by_item["i1"]]
    assert "paa_post" in cats1 and "gbp_post" in cats1 and "syndication" in cats1
    paa1 = next(r for r in by_item["i1"] if r["category"] == "paa_post")
    assert paa1["status"] == "collected" and paa1["url"] == "https://acme.com/x-cost/"
    assert paa1["source"] == "auto"

    # i2: run exists but not published → pending, no URL, no GBP row.
    paa2 = next(r for r in by_item["i2"] if r["category"] == "paa_post")
    assert paa2["status"] == "pending" and paa2["url"] is None
    assert all(r["category"] != "gbp_post" for r in by_item["i2"])

    # i3: no run at all → missing.
    assert by_item["i3"][0]["status"] == "missing"


# ── rebuild reconciliation ────────────────────────────────────────────────────


def test_merge_rows_first_build_seeds_and_rebuild_preserves_edits():
    auto = [{"category": "paa_post", "source": "auto"}]
    # First build: nothing exists yet.
    ins, keep, dele, has_seed = pm.merge_rows(auto, [])
    assert ins == auto and keep == [] and dele == [] and has_seed is False

    # Rebuild: an old auto row is replaced; seed + manual rows are preserved.
    existing = [
        {"id": "a-old", "source": "auto"},
        {"id": "s1", "source": "seed"},
        {"id": "m1", "source": "manual"},
    ]
    ins, keep, dele, has_seed = pm.merge_rows(auto, existing)
    assert dele == ["a-old"]
    assert set(keep) == {"s1", "m1"}
    assert has_seed is True  # caller will NOT re-seed


# ── cost rollup (reused Recipe Engine) ────────────────────────────────────────


def test_build_cost_summary_costs_mapped_rows_and_flags_off_menu():
    assets = pm.seed_authority_rows()  # gmbb_blast + wiki_cloud_stack map; rest don't
    summary = pm.build_cost_summary(assets)
    # gbp_blast ($5) + cloud_stack ($10) are the only priced seam bolts.
    assert summary["estimated_total"] == 15.0
    labels = {ln["task_type"] for ln in summary["lines"]}
    assert labels == {"gbp_blast", "cloud_stack"}
    not_est = {n["kind"] for n in summary["not_estimated"]}
    assert "rd_100" in not_est  # off-menu → honest "not estimated", never a fake $0


def test_build_cost_summary_none_when_nothing_maps():
    assets = [{"category": "authority", "kind": "rd_100", "cost_task_type": None,
               "label": "RD 100", "confidence_tag": "THEORY"}]
    summary = pm.build_cost_summary(assets)
    assert summary["estimated_total"] is None
    assert summary["not_estimated"][0]["kind"] == "rd_100"


# ── QA rollup ─────────────────────────────────────────────────────────────────


def test_qa_worst_severity_order():
    assert pm.qa_worst(["pass", "fail", "advisory"]) == "fail"
    assert pm.qa_worst(["pass", "advisory"]) == "advisory"
    assert pm.qa_worst(["pass"]) == "pass"
    assert pm.qa_worst(["pending", "skipped"]) is None
    assert pm.qa_worst([]) is None


def test_build_qa_summary_counts_content_only():
    assets = [
        {"category": "paa_post", "qa_verdict": "pass"},
        {"category": "syndication", "qa_verdict": "fail"},
        {"category": "paa_post", "qa_verdict": None},       # pending
        {"category": "gbp_post", "qa_verdict": None},        # not_applicable
        {"category": "image", "qa_verdict": None},           # not_applicable
        {"category": "authority", "qa_verdict": None},       # ignored
    ]
    s = pm.build_qa_summary(assets)
    assert s["content_assets"] == 5   # 2 paa + 1 syndication + gbp + image
    assert s["reviewed"] == 2 and s["pending"] == 1 and s["not_applicable"] == 2
    assert s["verdicts"] == {"pass": 1, "fail": 1}
    assert s["worst"] == "fail"


# ── export rendering ──────────────────────────────────────────────────────────


def test_export_rows_has_identity_header_guardrail_and_asset_rows():
    identity = pm.client_identity({"name": "Acme", "gbp": {"place_id": "ChIJ1"}})
    assets = [
        {"category": "paa_post", "source": "auto", "label": "PAA post — q",
         "url": "https://acme.com/q/", "status": "collected", "confidence_tag": None,
         "qa_verdict": "pass", "cost_task_type": None, "cost_quantity": None, "note": ""},
        {"category": "authority", "source": "seed", "label": "GMBB Blast",
         "url": None, "status": "planned", "confidence_tag": "PROVEN",
         "qa_verdict": None, "cost_task_type": "gbp_blast", "cost_quantity": 1,
         "note": "map-only"},
    ]
    rows = pm.export_rows(identity, assets, service_keyword="metal roof repair",
                          location="Denver, CO")
    flat = "\n".join("|".join(str(c) for c in r) for r in rows)
    assert rows[0][0] == "PAA → SEO Neo — Prep Sheet"
    assert "ChIJ1" in flat                      # identity header
    assert pm.GUARDRAIL_NOTE in flat            # boundary carried into the export
    assert "metal roof repair" in flat
    assert list(pm.export_columns) in rows      # the column header row
    assert "[PROVEN]" in flat                   # confidence tag rendered
    assert "$5.00" in flat                      # gbp_blast priced from the catalog


def test_export_payload_carries_guardrail_and_assets():
    payload = pm.export_payload(
        manifest={"status": "ready"}, identity={"business_name": "Acme"},
        assets=[{"category": "paa_post", "label": "PAA post", "url": "u",
                 "confidence_tag": "BELIEF"}],
        cost_summary={"estimated_total": 15.0}, qa_summary={"worst": "pass"},
        service_keyword="roof repair", generated_at="2026-09-15T00:00:00Z",
    )
    assert payload["guardrail"] == pm.GUARDRAIL_NOTE
    assert payload["status"] == "ready"
    assert payload["assets"][0]["confidence_tag"] == "BELIEF"
    assert payload["cost_summary"]["estimated_total"] == 15.0
