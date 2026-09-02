"""Module → code paths → in-app guide registry (pure, dependency-free).

The map behind DORA's guide sync (``services/guide_sync.py``): when a change
lands on ``main``, the CI reporter (``scripts/report_module_changes.py``) uses
this registry to work out WHICH modules the changed files belong to and WHICH
in-app guide (``guides.slug``, the Guides portal page) documents each one, and
whether the change is the kind a user could notice at all.

Two layers of classification, both deterministic:

1. ``is_user_facing(path)`` — the coarse gate. Tests, docs, CI, migrations,
   scripts, lockfiles, the seeded guide defaults, and the illustrated static
   field guides are never "user-facing code": a change confined to them can't
   alter what a user sees or what a module produces, so it never reaches DORA.
2. ``modules_for_paths(paths)`` — groups the surviving paths by module via the
   ``MODULES`` patterns (prefix rules end in ``/``; anything else is an
   ``fnmatch`` glob where ``*`` also crosses ``/``). A path can belong to more
   than one module (the shared reoptimize panel is Blog + Local SEO + Ecommerce);
   a path that matches no module is reported under ``unmapped`` so a new module
   can't silently fall outside the sync.

This module MUST stay importable with no app dependencies (no ``config``, no
Supabase): the CI reporter runs it from a bare GitHub Actions runner.
"""

from __future__ import annotations

import re
from fnmatch import fnmatchcase

_DOT_SLASH = re.compile(r"^(?:\./)+")

_P = "writer/platform-api/"
_F = "frontend/src/"
_N = "writer/nlp-api/"
_PL = "writer/pipeline-api/"

# Paths that never count as a user-facing change. Prefix rules end in "/";
# the rest are globs. Order doesn't matter — any match ignores the path.
IGNORED_PATTERNS: tuple[str, ...] = (
    "docs/",
    ".github/",
    "writer/supabase/",
    "*/tests/*",
    "*/agent_docs/*",
    "*/scripts/*",
    "*.md",
    "*.lock",
    "*lock.json",
    "*requirements*.txt",
    "*/Dockerfile",
    "Dockerfile",
    "*railway.toml",
    "*railway.json",
    "netlify*",
    "*.test.ts",
    "*.test.tsx",
    "*.spec.ts",
    "*.spec.tsx",
    "*/pyproject.toml",
    "*/.gitignore",
    ".gitignore",
    "skills-lock.json",
    # The seeded default guides and the illustrated field guides ARE the docs —
    # a change there is a documentation edit, not a module change.
    _P + "services/guide_seed.py",
    "frontend/public/field-guides/*",
    # The prototype reference copy — never ships.
    "local-seo-writer/",
)

# module_key → {label, guide_slug, patterns}. guide_slug is the `guides.slug`
# of the in-app Guides-portal page for that module (services/guide_seed.py).
MODULES: dict[str, dict] = {
    "blog_writer": {
        "label": "Blog Writer",
        "guide_slug": "blog-writer",
        "patterns": (
            _PL + "modules/", _PL + "main.py",
            _P + "routers/runs.py", _P + "routers/publish.py", _P + "routers/briefs.py",
            _P + "routers/silos.py", _P + "routers/files.py", _P + "routers/score_existing.py",
            _P + "services/orchestrator.py", _P + "services/run_dispatch.py",
            _P + "services/run_retry.py", _P + "services/blog_page_score.py",
            _P + "services/blog_jsonld.py", _P + "services/blog_media/",
            _P + "services/illustration.py", _P + "services/silo_*.py",
            _P + "services/score_external.py", _P + "services/wordpress_publish.py",
            _P + "services/github_publish.py", _P + "services/github_infer.py",
            _P + "services/google_docs.py", _P + "services/publish_targeting.py",
            _P + "services/content_batch.py", _P + "services/internal_linking.py",
            _P + "routers/internal_linking.py",
            _F + "pages/Runs.tsx", _F + "pages/RunDetail.tsx", _F + "pages/Articles.tsx",
            _F + "pages/Silos.tsx", _F + "pages/InternalLinks.tsx", _F + "pages/ServicePages.tsx",
            _F + "pages/LocationPages.tsx", _F + "components/ServicePageRunView.tsx",
            _F + "components/silos/", _F + "components/publish/", _F + "components/score/",
            _F + "components/reoptimize/", _F + "components/FeaturedImagePicker.tsx",
            _F + "components/BriefCacheDecisionModal.tsx",
        ),
    },
    "local_seo": {
        "label": "Local SEO content",
        "guide_slug": "local-seo",
        "patterns": (
            _N + "main.py", _N + "length_fit.py", _N + "page_spec.py", _N + "section_edit.py",
            _N + "voice_card.py", _N + "url_filter.py", _N + "blog_structure.py",
            _P + "routers/local_seo.py", _P + "routers/local_seo_matrix.py",
            _P + "routers/wheelhouse.py",
            _P + "services/local_seo_*.py", _P + "services/local_relevance.py",
            _P + "services/page_spec*.py", _P + "services/page_structure_render.py",
            _P + "services/analysis_cache.py", _P + "services/voice_card_service.py",
            _P + "services/service_page_*.py", _P + "services/structure_gate.py",
            _P + "services/wheelhouse_*.py", _P + "services/target_cities.py",
            _P + "services/site_page_index.py",
            _F + "pages/LocalSeoContent.tsx", _F + "pages/Wheelhouse.tsx",
            _F + "components/localseo/", _F + "components/reoptimize/",
            _F + "components/EntityProviderSelect.tsx",
        ),
    },
    "ecommerce": {
        "label": "Ecommerce Writer",
        "guide_slug": "ecommerce",
        "patterns": (
            _N + "ecommerce_*.py", _P + "routers/ecommerce.py", _P + "services/ecommerce_*.py",
            _F + "pages/EcommerceProduct.tsx", _F + "components/ecommerce/",
            _F + "components/reoptimize/",
        ),
    },
    "keyword_research": {
        "label": "Keyword Research",
        "guide_slug": "keyword-research",
        "patterns": (
            _P + "routers/keyword_research.py", _P + "services/keyword_research*.py",
            _P + "services/keyword_topic_*.py", _F + "pages/KeywordResearch.tsx",
        ),
    },
    "topic_fanout": {
        "label": "Topic Fanout (Mass Posts)",
        "guide_slug": "topic-fanout",
        "patterns": (
            _P + "fanout/", _F + "fanout/", _P + "routers/content_schedule.py",
            _P + "services/content_schedule_*.py", _P + "services/content_calendar.py",
            _F + "pages/ContentScheduler.tsx", _F + "pages/ContentCalendar.tsx",
            _F + "components/scheduler/",
        ),
    },
    "content_syndication": {
        "label": "Content Syndication",
        "guide_slug": "content-syndication",
        "patterns": (
            _P + "routers/syndication.py", _P + "services/syndication_*.py",
            _F + "pages/Syndication.tsx",
        ),
    },
    "gbp_posts": {
        "label": "GBP Posts",
        "guide_slug": "gbp-posts",
        "patterns": (
            _P + "routers/gbp_posts.py", _P + "routers/gbp_oauth.py",
            _P + "services/gbp_posts_*.py", _P + "services/gbp_oauth.py",
            _P + "services/gbp_auth.py", _F + "pages/GbpPosts.tsx",
        ),
    },
    "website_builder": {
        "label": "Website Builder",
        "guide_slug": "website-builder",
        "patterns": (
            _P + "routers/websites.py", _P + "services/website_*.py", "site-template/",
            _F + "pages/Websites.tsx", _F + "pages/WebsiteBuilder.tsx", _F + "components/website/",
        ),
    },
    "rank_tracker": {
        "label": "Organic Rank Tracker",
        "guide_slug": "rank-tracker",
        "patterns": (
            _P + "routers/rank.py", _P + "routers/gsc.py", _P + "routers/forecast.py",
            _P + "services/rank_*.py", _P + "services/rankability.py",
            _P + "services/gsc_service.py", _P + "services/gsc_ingest.py",
            _P + "services/dataforseo_rank.py", _P + "services/keyword_market.py",
            _P + "services/serp_snapshot.py", _P + "services/serp_trends.py",
            _P + "services/forecasting.py", _P + "services/trend_watch.py",
            _F + "pages/Rankings.tsx", _F + "pages/RankReport.tsx", _F + "pages/Forecast.tsx",
            _F + "components/rankings/",
        ),
    },
    "maps_geogrid": {
        "label": "Maps Geo-Grid (Local Dominator)",
        "guide_slug": "maps-geogrid",
        "patterns": (
            _P + "routers/maps.py", _P + "services/maps_*.py", _P + "services/local_dominator.py",
            _P + "services/competitor_gbp.py", _P + "services/dataforseo_reviews.py",
            _P + "services/review_analytics.py",
            _F + "pages/MapsGeogrid.tsx", _F + "pages/MapsReport.tsx", _F + "components/maps/",
        ),
    },
    "ai_visibility": {
        "label": "AI Visibility (Brand Strength)",
        "guide_slug": "ai-visibility",
        "patterns": (
            _P + "routers/brand.py", _P + "services/brand_scan.py", _P + "services/brand_service.py",
            _P + "services/brand_insights.py", _P + "services/brand_schedule.py",
            _P + "services/brand_report.py", _P + "services/brand_report_html.py",
            _P + "services/brand_alerts.py", _P + "services/brand_search.py",
            _P + "services/lead_valuation.py",
            _F + "pages/AiVisibility.tsx", _F + "components/aivisibility/",
        ),
    },
    "domain_intelligence": {
        "label": "Domain Intelligence",
        "guide_slug": "domain-intelligence",
        "patterns": (
            _P + "routers/domain_intel.py", _P + "routers/backlinks.py", _P + "routers/competitors.py",
            _P + "services/domain_intel.py", _P + "services/dataforseo_labs.py",
            _P + "services/backlink_*.py", _P + "services/backlinks_api.py",
            _P + "services/competitor_intel.py", _P + "services/competitor_page_intel.py",
            _P + "services/authority_report.py",
            _F + "pages/DomainIntel.tsx", _F + "pages/Backlinks.tsx", _F + "pages/Competitors.tsx",
            _F + "components/AuthorityReport.tsx",
        ),
    },
    "leadoff": {
        "label": "LeadOff (market intelligence)",
        "guide_slug": "leadoff",
        "patterns": (
            _P + "routers/leadoff.py", _P + "routers/outreach.py",
            _P + "services/leadoff*.py", _P + "services/census_demand.py",
            _P + "services/outreach*.py", "outreach/",
            _F + "pages/LeadOff.tsx", _F + "pages/Outreach.tsx", _F + "pages/OutreachLeads.tsx",
            _F + "components/leadoff/", _F + "components/outreach/",
        ),
    },
    "gsc_research": {
        "label": "GSC Research",
        "guide_slug": "gsc-research",
        "patterns": (
            _P + "routers/gsc_research.py", _P + "services/gsc_research.py",
            _F + "pages/GscResearch.tsx",
        ),
    },
    "everhour_time": {
        "label": "Everhour Time Tracking",
        "guide_slug": "everhour-time",
        "patterns": (
            _P + "routers/everhour.py", _P + "services/everhour_*.py",
            _F + "components/EverhourTimeCard.tsx",
        ),
    },
    "client_reports": {
        "label": "Client Reports",
        "guide_slug": "client-reports",
        "patterns": (
            _P + "routers/reports.py", _P + "routers/gbp_metrics.py", _P + "routers/ga4.py",
            _P + "routers/pulse.py",
            _P + "services/client_report*.py", _P + "services/gbp_metrics_*.py",
            _P + "services/gbp_performance_service.py", _P + "services/ga4_*.py",
            _P + "services/client_pulse.py",
            _F + "pages/ClientReports.tsx", _F + "pages/GbpMetrics.tsx",
            _F + "components/reports/", _F + "components/WeeklyPulse.tsx",
        ),
    },
    "task_manager": {
        "label": "Task Manager (the delivery board)",
        "guide_slug": "task-manager",
        "patterns": (
            _P + "routers/tasks.py", _P + "routers/deliverables.py", _P + "routers/recipe.py",
            _P + "services/task_*.py", _P + "services/pm_signals.py",
            _P + "services/deliverables_sheet.py", _P + "services/recipe_engine.py",
            _P + "services/content_ready.py",
            _F + "pages/Tasks.tsx", _F + "pages/MyTasks.tsx", _F + "pages/TaskLibrary.tsx",
            _F + "pages/TeamWorkload.tsx", _F + "pages/Team.tsx", _F + "pages/TaskPlan.tsx",
            _F + "components/tasks/",
        ),
    },
    "pace_qa": {
        "label": "PACE & QA",
        "guide_slug": "pace-qa",
        "patterns": (
            _P + "routers/pace.py", _P + "routers/qa.py",
            _P + "services/pace_*.py", _P + "services/pm_assign.py", _P + "services/qa_*.py",
            _P + "services/agent_bus.py",
            _F + "pages/Pace.tsx", _F + "pages/PaceLog.tsx", _F + "pages/Qa.tsx",
            _F + "components/PaceChat.tsx", _F + "components/QaChat.tsx", _F + "components/pace/",
        ),
    },
    "sermastr": {
        "label": "SerMaStr",
        "guide_slug": "sermastr",
        "patterns": (
            _P + "routers/assistant.py", _P + "routers/strategist.py",
            _P + "routers/interventions.py", _P + "routers/slack_events.py",
            _P + "services/slack_assistant/", _P + "services/assistant_chat.py",
            _P + "services/assistant_store.py", _P + "services/strategist*.py",
            _P + "services/strategy_*.py", _P + "services/goal_recovery.py",
            _P + "services/goal_escalation.py", _P + "services/sermastr_audit.py",
            _P + "services/sop_library.py", _P + "services/interventions.py",
            _P + "services/autonomy_*.py", _P + "services/plan_handoff.py",
            _F + "pages/Assistant.tsx", _F + "pages/SermastrLog.tsx",
            _F + "components/SerMastrChat.tsx", _F + "components/StrategistReview.tsx",
            _F + "components/InterventionOutcomes.tsx", _F + "components/MemoryEditor.tsx",
            _F + "components/ConversationHistory.tsx",
        ),
    },
    "dora": {
        "label": "DORA (Director of Operations)",
        "guide_slug": "dora",
        "patterns": (
            _P + "routers/director.py", _P + "services/director/", _P + "services/director_agent.py",
            _P + "services/guide_sync.py", _P + "services/guide_registry.py",
            _F + "pages/Director.tsx", _F + "components/DirectorChat.tsx",
        ),
    },
    "action_plan": {
        "label": "Action Plan & Campaign Goals",
        "guide_slug": "action-plan",
        "patterns": (
            _P + "routers/reopt.py", _P + "routers/goals.py", _P + "routers/citations.py",
            _P + "routers/freeze.py",
            _P + "services/reopt_planner.py", _P + "services/drop_classifier.py",
            _P + "services/response_episodes.py", _P + "services/campaign_goals.py",
            _P + "services/offpage_agent.py", _P + "services/citation_check.py",
            _P + "services/freeze.py", _P + "services/gbp_audit.py",
            _P + "services/content_intel.py", _P + "services/page_backlink_intel.py",
            _F + "pages/ActionPlan.tsx", _F + "pages/CampaignGoals.tsx",
            _F + "pages/Citations.tsx", _F + "components/FreezeBanner.tsx",
        ),
    },
    "sops_playbook": {
        "label": "SOPs & Playbook",
        "guide_slug": "sops-playbook",
        "patterns": (
            _P + "routers/sops.py", _P + "services/sop_store.py", _F + "pages/Sops.tsx",
        ),
    },
    "client_setup": {
        "label": "Client setup & context",
        "guide_slug": "client-setup",
        "patterns": (
            _P + "routers/clients.py", _P + "routers/brand_voice.py", _P + "routers/icp.py",
            _P + "routers/users.py",
            _P + "services/gbp_service.py", _P + "services/gbp_locations_service.py",
            _P + "services/gbp_invitations.py", _P + "services/gbp_reviews*.py",
            _P + "services/gbp_search_keywords.py", _P + "services/brand_voice_service.py",
            _P + "services/brand_analysis.py", _P + "services/icp_service.py",
            _P + "services/page_structure_scraper.py", _P + "services/page_structure_manual.py",
            _P + "services/website_scraper.py", _P + "services/file_parser.py",
            _F + "pages/ClientForm.tsx", _F + "pages/Clients.tsx", _F + "pages/ClientWorkspace.tsx",
            _F + "pages/ClientContent.tsx", _F + "pages/BrandVoice.tsx", _F + "pages/Icp.tsx",
            _F + "components/brandvoice/", _F + "components/icp/", _F + "components/GbpPicker.tsx",
            _F + "components/coverage/",
        ),
    },
    "getting_started": {
        "label": "Getting started (the suite shell)",
        "guide_slug": "getting-started",
        "patterns": (
            _P + "routers/dashboard.py", _P + "routers/activity.py", _P + "routers/notifications.py",
            _P + "services/activity.py", _P + "services/notifications.py",
            _F + "pages/Home.tsx", _F + "pages/Activity.tsx", _F + "pages/Login.tsx",
            _F + "pages/SetPassword.tsx", _F + "App.tsx",
            _F + "components/Layout.tsx", _F + "components/NotificationBell.tsx",
            _F + "components/ClientNotifications.tsx", _F + "components/FeedbackButton.tsx",
            # The Guides portal itself (the pages DORA keeps current).
            _P + "routers/guides.py", _P + "services/guide_store.py", _F + "pages/Guides.tsx",
            _F + "components/Markdown.tsx", _F + "components/ErrorDetails.tsx",
        ),
    },
    "asana_tasks": {
        "label": "Asana Tasks (legacy)",
        "guide_slug": "asana-tasks",
        "patterns": (
            _P + "routers/asana.py", _P + "services/asana_*.py", _F + "pages/AsanaTasks.tsx",
        ),
    },
}

UNMAPPED = "unmapped"


def _clean(path: str) -> str:
    """Strip a leading ``./`` (git/CI output) without eating a dot-directory
    like ``.github/``."""
    return _DOT_SLASH.sub("", (path or "").strip())


def _matches(path: str, pattern: str) -> bool:
    if pattern.endswith("/"):
        return path.startswith(pattern)
    return fnmatchcase(path, pattern)


def is_user_facing(path: str) -> bool:
    """Whether a changed file can alter what a user sees or what a module
    produces. False for tests, docs, CI, migrations, scripts, lockfiles, the
    seeded guides, and the static field guides."""
    path = _clean(path)
    if not path:
        return False
    return not any(_matches(path, pat) for pat in IGNORED_PATTERNS)


def modules_for_path(path: str) -> list[str]:
    """Every module key whose patterns match ``path`` (a shared component can
    belong to several). Empty when nothing matches."""
    path = _clean(path)
    return [key for key, mod in MODULES.items() if any(_matches(path, p) for p in mod["patterns"])]


def modules_for_paths(paths: list[str]) -> dict[str, list[str]]:
    """Group the user-facing paths by module key → sorted paths. Paths that
    match no module land under ``UNMAPPED`` (never dropped silently). Ignored
    paths are excluded entirely."""
    out: dict[str, list[str]] = {}
    for raw in paths or []:
        path = _clean(raw)
        if not path or not is_user_facing(path):
            continue
        keys = modules_for_path(path) or [UNMAPPED]
        for key in keys:
            out.setdefault(key, []).append(path)
    return {key: sorted(set(v)) for key, v in out.items()}


def guide_slug_for(module_key: str) -> str | None:
    mod = MODULES.get(module_key)
    return mod["guide_slug"] if mod else None


def module_label(module_key: str) -> str:
    mod = MODULES.get(module_key)
    return mod["label"] if mod else module_key
