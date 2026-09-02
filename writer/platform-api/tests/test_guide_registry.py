"""Unit tests for services.guide_registry — the pure module → paths → guide
map behind DORA's guide sync: the user-facing gate, module grouping (incl. a
shared component belonging to several modules), the unmapped bucket (never a
silent drop), and registry integrity (every guide_slug is a seeded guide)."""

from __future__ import annotations

from services import guide_registry as R


def test_ignored_paths_are_not_user_facing():
    for path in [
        "docs/dora-user-guide.md",
        ".github/workflows/guide-sync.yml",
        "writer/supabase/migrations/20260902180000_guide_sync.sql",
        "writer/platform-api/tests/test_guide_sync.py",
        "writer/nlp-api/tests/test_voice_localize.py",
        "writer/platform-api/agent_docs/sops/x.md",
        "writer/platform-api/scripts/report_module_changes.py",
        "HANDOFF.md",
        "frontend/package-lock.json",
        "writer/platform-api/requirements.txt",
        "writer/platform-api/Dockerfile",
        "writer/platform-api/services/guide_seed.py",
        "frontend/public/field-guides/dora.html",
        "local-seo-writer/app.py",
        "",
    ]:
        assert not R.is_user_facing(path), path


def test_code_paths_are_user_facing():
    for path in [
        "writer/platform-api/routers/rank.py",
        "writer/platform-api/services/director/reconcile.py",
        "frontend/src/pages/Rankings.tsx",
        "writer/nlp-api/main.py",
        "site-template/src/pages/index.astro",
    ]:
        assert R.is_user_facing(path), path


def test_modules_for_path_maps_known_files():
    assert R.modules_for_path("writer/platform-api/routers/rank.py") == ["rank_tracker"]
    assert R.modules_for_path("frontend/src/components/rankings/RankOverview.tsx") == ["rank_tracker"]
    assert R.modules_for_path("writer/platform-api/services/director/seams.py") == ["dora"]
    assert R.modules_for_path("writer/platform-api/services/guide_sync.py") == ["dora"]
    assert R.modules_for_path("writer/nlp-api/ecommerce_facts.py") == ["ecommerce"]
    assert R.modules_for_path("writer/platform-api/fanout/api/schedules.py") == ["topic_fanout"]
    assert R.modules_for_path("frontend/src/fanout/owner/views/ArticlesView.tsx") == ["topic_fanout"]
    assert R.modules_for_path("site-template/src/lib/layouts.ts") == ["website_builder"]


def test_shared_component_belongs_to_several_modules():
    keys = R.modules_for_path("frontend/src/components/reoptimize/ReoptimizePanel.tsx")
    assert set(keys) == {"blog_writer", "local_seo", "ecommerce"}


def test_modules_for_paths_groups_and_buckets_unmapped():
    grouped = R.modules_for_paths([
        "writer/platform-api/routers/rank.py",
        "frontend/src/pages/Rankings.tsx",
        "writer/platform-api/tests/test_rank_status.py",   # ignored
        "docs/organic-rank-tracker-user-guide.md",          # ignored
        "writer/platform-api/services/report_llm.py",       # shared infra → unmapped
        "./frontend/src/pages/Rankings.tsx",                # dedupes after ./ strip
    ])
    assert grouped["rank_tracker"] == ["frontend/src/pages/Rankings.tsx", "writer/platform-api/routers/rank.py"]
    assert grouped[R.UNMAPPED] == ["writer/platform-api/services/report_llm.py"]
    assert "test_rank_status" not in str(grouped)


def test_modules_for_paths_drops_only_ignored_never_silently_unmapped():
    grouped = R.modules_for_paths(["docs/x.md", "writer/platform-api/tests/t.py"])
    assert grouped == {}


def test_registry_integrity_guide_slugs_are_seeded_guides():
    from services.guide_seed import DEFAULT_GUIDES

    seeded = {g["slug"] for g in DEFAULT_GUIDES}
    for key, mod in R.MODULES.items():
        assert mod["guide_slug"] in seeded, f"{key} → unknown guide slug {mod['guide_slug']}"
        assert mod["patterns"], key
        assert R.guide_slug_for(key) == mod["guide_slug"]
        assert R.module_label(key) == mod["label"]
    assert R.guide_slug_for("nope") is None
    assert R.module_label("nope") == "nope"


def test_registry_is_importable_without_app_dependencies():
    # The CI reporter runs this module on a bare runner — it must not pull in
    # config/Supabase transitively.
    import importlib
    import sys

    src = importlib.util.find_spec("services.guide_registry").origin
    text = open(src, encoding="utf-8").read()
    for forbidden in ("from config", "import config", "import supabase", "from supabase", "from db.", "from services."):
        assert forbidden not in text, forbidden
    assert "services.guide_registry" in sys.modules
