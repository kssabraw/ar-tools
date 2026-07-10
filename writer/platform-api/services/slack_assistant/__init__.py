"""Slack conversational assistant — "SerMastr".

Two-way Slack, **channel mode**: SerMastr lives in a dedicated channel, so Slack
POSTs a `message` event to `/slack/events` for *every* message there (no @mention
needed). We answer each plain human message — resolve which client it's about,
assemble a cross-module context covering every workspace module (rank trackers,
Maps geo-grid, AI visibility, content, keyword research, task plan, citations,
syndication, reports, SOPs, Asana, health guards, strategist reviews, setup),
fold in the thread's prior turns for
continuity, ask Claude, and post the answer back **in-thread**. The bot's own
posts (rank-drop alerts etc.) and other bots are ignored, so it never loops.

Answers are grounded in the suite's own data, plus Anthropic's server-side
web_search tool (config-gated) for public info the suite doesn't hold —
third-party reviews, competitor sites, industry news — with campaign metrics
still sourced exclusively from the cross-module context.

Q&A plus an action registry (_ACTIONS): the assistant has admin-level write
access — it can trigger work (scans, research, a strategist review, client
reports, an Asana task-plan push), manage the client's Asana board, edit the
client profile (Setup-page scalars + target cities), and manage campaign state
(tracked keywords, AI-visibility keywords/competitors, campaign goals). Every
paid or side-effecting action is staged behind an explicit reply-*yes* confirm
that names the exact change. Anyone in the workspace can ask (per the product
decision); inbound requests are verified by Slack's request signature so the
public endpoint can't be spoofed.

Split: pure helpers (signature verify, mention stripping, client resolution,
history formatting) are import-light and unit-tested; the context build + thread
fetch + Claude call + Slack post do I/O.

Package layout (split 2026-07-10 from the original single module — a pure
move, no behavior change):
- helpers.py — pure, I/O-free helpers (signature verify, client resolution,
  formatting, the portfolio/affirmative/SOP-grounding gates)
- prompts.py — the system prompts (single-client, portfolio, web style)
- context.py — cross-module context assembly (DB reads) + durable memory
- actions.py — the action registry (_ACTIONS): runners, staging, matchers
- llm.py — Claude + Slack I/O: the interpret loop, live-data tools, and
  message handling

Everything is re-exported below, so `from services import slack_assistant`
keeps working unchanged. NOTE for tests: monkeypatch the DEFINING submodule
(e.g. `setattr(actions, "get_supabase", …)`) — patching a re-exported name on
this package does not rebind the implementation module's global.
"""

from services.slack_assistant.actions import (
    _ACTION_TOOLS,
    _ACTIONS,
    _PROFILE_FIELDS,
    _REPORT_TYPES,
    _SOP_TASK_ENUM,
    _act_add_ai_competitor,
    _act_add_ai_keywords,
    _act_add_cities,
    _act_add_goal,
    _act_add_task,
    _act_add_tracked_keywords,
    _act_ai_scan,
    _act_complete_task,
    _act_generate_report,
    _act_gsc_research,
    _act_live_serp,
    _act_maps_scan,
    _act_push_task_plan,
    _act_rebuild_plan,
    _act_remove_ai_competitor,
    _act_remove_ai_keyword,
    _act_remove_cities,
    _act_remove_goal,
    _act_remove_task,
    _act_remove_tracked_keyword,
    _act_strategy_review,
    _act_update_profile,
    _asana_ready,
    _clean_list,
    _client_row,
    _fmt_profile_value,
    _pending,
    _stage_add_ai_competitor,
    _stage_add_ai_keywords,
    _stage_add_cities,
    _stage_add_goal,
    _stage_add_task,
    _stage_add_tracked_keywords,
    _stage_complete_task,
    _stage_generate_report,
    _stage_live_serp,
    _stage_pick_task,
    _stage_remove_ai_competitor,
    _stage_remove_ai_keyword,
    _stage_remove_cities,
    _stage_remove_goal,
    _stage_remove_task,
    _stage_remove_tracked_keyword,
    _stage_update_profile,
    coerce_profile_value,
    drop_cities,
    match_named,
    match_open_tasks,
    merge_cities,
)
from services.slack_assistant.context import (
    _CONTEXT_PROVIDERS,
    _MEMORY_CONTEXT_LIMIT,
    _MEMORY_KEEP,
    _MEMORY_TOOL,
    _ctx_ai_visibility,
    _ctx_asana,
    _ctx_campaign_goals,
    _ctx_citations,
    _ctx_competitors,
    _ctx_content,
    _ctx_forecast,
    _ctx_health,
    _ctx_keyword_research,
    _ctx_maps,
    _ctx_memories,
    _ctx_organic_rank,
    _ctx_reports,
    _ctx_setup,
    _ctx_sops,
    _ctx_strategist,
    _ctx_syndication,
    _ctx_task_plan,
    _ctx_trends,
    _run_remember,
    build_context,
    build_portfolio_context,
)
from services.slack_assistant.helpers import (
    _MENTION_RE,
    _PORTFOLIO_RE,
    _SIG_MAX_SKEW_SECONDS,
    _SOP_DOMAIN_HINTS,
    _SOP_HINT_RE,
    format_context,
    format_history,
    is_affirmative,
    is_local_client,
    resolve_client,
    sop_domains,
    strip_mention,
    verify_slack_signature,
    wants_portfolio,
    wants_sop_grounding,
    weak_cities,
)
from services.slack_assistant.llm import (
    _BUSY_REPLY,
    _CAPACITY_STATUS_CODES,
    _LIVE_GSC_RESULT_CHARS,
    _LIVE_GSC_ROUNDS,
    _LIVE_GSC_TOOL,
    _LIVE_GSC_TOP,
    _LLM_MAX_RETRIES,
    _LLM_TIMEOUT,
    _PAUSE_TURN_CONTINUATIONS,
    _THREAD_HISTORY_LIMIT,
    _TIMEOUT,
    _create_with_continuation,
    _one_llm_call,
    _read_sop_tool,
    _run_action,
    _run_live_gsc,
    build_llm_tools,
    extract_interpretation,
    fetch_thread_history,
    handle_message,
    interpret,
    interpret_portfolio,
    post_message,
)
from services.slack_assistant.prompts import _PORTFOLIO_SYSTEM, _SYSTEM, _WEB_STYLE
