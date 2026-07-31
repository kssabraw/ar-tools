"""Pure helpers (no I/O) — unit-tested.

Slack signature verification, mention stripping, client resolution,
context/history formatting, and the local-campaign / portfolio / affirmative /
SOP-grounding gates.

Part of the `services.slack_assistant` package; see its docstring for the
full picture."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from typing import Optional

_MENTION_RE = re.compile(r"<@[A-Z0-9]+>")
_SIG_MAX_SKEW_SECONDS = 60 * 5  # reject events older than 5 min (replay guard)


def verify_slack_signature(
    signing_secret: str, timestamp: str, raw_body: str, signature: str, now_ts: int
) -> bool:
    """True iff the Slack request signature is valid and recent. Pure.

    Slack signs `v0:{timestamp}:{body}` with HMAC-SHA256 over the signing secret.
    Fail-closed: a missing secret/signature/timestamp, a stale timestamp (replay),
    or any parse error returns False.
    """
    if not (signing_secret and timestamp and signature):
        return False
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs(now_ts - ts) > _SIG_MAX_SKEW_SECONDS:
        return False
    basestring = f"v0:{timestamp}:{raw_body}".encode()
    expected = "v0=" + hmac.new(signing_secret.encode(), basestring, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def strip_mention(text: str) -> str:
    """Remove Slack user mentions (`<@U123>`) and collapse whitespace. Pure."""
    return _MENTION_RE.sub("", text or "").strip()


def resolve_client(message: str, clients: list[dict]) -> Optional[dict]:
    """Pick the client a message is about by matching client names. Pure.

    Prefers the longest client name that appears as a whole-word substring of the
    message (so "Acme Plumbing" wins over "Acme" when both exist). Falls back to a
    token-overlap match (any distinctive name word present). Returns None when
    nothing matches — the caller then asks the user to name the client.
    """
    msg = (message or "").lower()
    if not msg:
        return None
    # 1) Whole-name substring, longest name first.
    named = sorted(
        (c for c in clients if (c.get("name") or "").strip()),
        key=lambda c: len(c["name"]),
        reverse=True,
    )
    for c in named:
        name = c["name"].lower()
        if re.search(rf"\b{re.escape(name)}\b", msg):
            return c
    # 2) Distinctive-token overlap (ignore generic words).
    stop = {"the", "and", "of", "for", "co", "inc", "llc", "ltd", "group", "services", "service"}
    best, best_hits = None, 0
    for c in named:
        tokens = {t for t in re.split(r"\W+", c["name"].lower()) if len(t) > 2 and t not in stop}
        hits = sum(1 for t in tokens if re.search(rf"\b{re.escape(t)}\b", msg))
        if hits > best_hits:
            best, best_hits = c, hits
    return best if best_hits else None


def format_context(client: dict, context: dict) -> str:
    """Compact JSON-ish context block for the LLM prompt. Pure."""
    payload = {
        "client": {"name": client.get("name"), "website": client.get("website_url")},
        **context,
    }
    return json.dumps(payload, default=str, ensure_ascii=False)


def weak_cities(report_weak_locations) -> list[str]:
    """City names from a Maps result's `report_weak_locations`. Pure, shape-tolerant.

    The stored value is the geocoder's object — `{geocoded, capped, weak_areas:[...]}`
    — but tolerate a bare list of area dicts or None/other too (so a shape change
    never throws and drops the whole module)."""
    rwl = report_weak_locations
    if isinstance(rwl, dict):
        areas = rwl.get("weak_areas") or []
    elif isinstance(rwl, list):
        areas = rwl
    else:
        areas = []
    out: list[str] = []
    for area in areas[:5]:
        city = area.get("city") if isinstance(area, dict) else None
        if city:
            out.append(city)
    return out


# ── Maps geo-grid trend series (shared by the context provider + maps_history) ──
def maps_series_point(result_row: dict, scanned_at) -> dict:
    """One geo-grid scan's coverage numbers for a keyword. Pure, shape-tolerant.

    pack_presence_pct (top-3 pins / total) is the honest coverage number;
    average_rank is over FOUND pins only, so it must be read against
    found_pins/total_pins, never on its own."""
    total = result_row.get("total_pins") or 0
    top3 = result_row.get("top3_pins") or 0
    return {
        "scanned_at": scanned_at,
        "average_rank": result_row.get("average_rank"),
        "found_pins": result_row.get("found_pins"),
        "total_pins": total,
        "top3_pins": top3,
        "pack_presence_pct": round(100.0 * top3 / total, 1) if total else None,
    }


def group_maps_series(scans: list[dict], results: list[dict]) -> dict[str, list[dict]]:
    """Group per-keyword scan results into a series oldest→newest. Pure.

    ``scans`` are maps_scans rows ({id, completed_at, …}); ``results`` are
    maps_scan_results rows ({scan_id, keyword, …}). Results whose scan isn't in
    ``scans`` are dropped. Returns {keyword: [point, …]} (points from
    ``maps_series_point``), each list sorted oldest→newest by scan date."""
    meta = {s["id"]: s for s in scans}
    by_kw: dict[str, list[tuple]] = {}
    for r in results:
        s = meta.get(r.get("scan_id"))
        if not s:
            continue
        when = s.get("completed_at") or ""
        by_kw.setdefault(r.get("keyword"), []).append((when, maps_series_point(r, when or None)))
    return {
        kw: [pt for _, pt in sorted(pts, key=lambda t: t[0])]
        for kw, pts in by_kw.items()
    }


def _maps_direction(presence_delta, rank_delta) -> str:
    """Trajectory from a keyword's latest-vs-previous deltas. Pure.

    Coverage first: a ≥3-point pack-presence move decides it; else a ≥0.3
    average-rank move (lower rank = better); else flat."""
    if presence_delta is not None and abs(presence_delta) >= 3:
        return "improving" if presence_delta > 0 else "declining"
    if rank_delta is not None and abs(rank_delta) >= 0.3:
        return "improving" if rank_delta < 0 else "declining"
    return "flat"


def build_maps_trend(keyword: str, series: list[dict]) -> dict:
    """Compact latest-vs-previous trend summary for one keyword. Pure.

    ``series`` is oldest→newest ``maps_series_point`` dicts (≥1). Emits the
    latest coverage numbers, latest-vs-previous deltas (negative average_rank_delta
    = improved), a direction, and the pack-presence spark over the window."""
    latest = series[-1]
    prev = series[-2] if len(series) >= 2 else None
    out: dict = {
        "keyword": keyword,
        "scans": len(series),
        "pack_presence_pct": latest["pack_presence_pct"],
        "average_rank": latest["average_rank"],
        "found_pins": latest["found_pins"],
        "total_pins": latest["total_pins"],
        "pack_presence_series": [p["pack_presence_pct"] for p in series],
    }
    if prev is not None:
        pd = rd = None
        if latest["pack_presence_pct"] is not None and prev["pack_presence_pct"] is not None:
            pd = round(latest["pack_presence_pct"] - prev["pack_presence_pct"], 1)
            out["pack_presence_delta"] = pd
        if latest["average_rank"] is not None and prev["average_rank"] is not None:
            rd = round(latest["average_rank"] - prev["average_rank"], 2)
            out["average_rank_delta"] = rd
        out["direction"] = _maps_direction(pd, rd)
    return out


def format_history(history: list[dict]) -> str:
    """Render prior thread turns as a plain transcript for the prompt. Pure.

    Folded into the user message (not structured messages) so multi-person threads
    with no strict user/assistant alternation don't violate the LLM's role rules.
    Each item is {"role": "assistant"|"user", "content": str}.
    """
    lines = []
    for h in history:
        who = "SerMastr" if h.get("role") == "assistant" else "Teammate"
        text = (h.get("content") or "").strip()
        if text:
            lines.append(f"{who}: {text}")
    return "\n".join(lines)


def is_local_client(client: dict, local_seo_pages: int = 0, maps_scans: int = 0) -> bool:
    """Whether local-only setup (target cities, suburb targeting) applies to this
    client at all. Pure.

    Any positive signal counts: a GBP attached, the service-area-business flag,
    a business address or manual target cities typed on the client, or actual
    local work in the suite (Local SEO pages, Maps geo-grid scans). No signal →
    not a local campaign, and empty target cities is the correct state, not a
    gap. `clients.client_type` is deliberately not read — it defaults to
    'local' for every client, so it can't distinguish anything.
    """
    gbp = client.get("gbp") or {}
    return bool(
        gbp.get("business_name")
        or gbp.get("place_id")
        or client.get("is_sab")
        or client.get("business_location")
        or client.get("target_cities")
        or local_seo_pages
        or maps_scans
    )


_PORTFOLIO_RE = re.compile(
    r"\b(all|which|any|our|the|every|across)\s+(of\s+(our|the)\s+)?clients\b"
    r"|\bportfolio\b|\bevery\s+client\b|\bacross\s+the\s+board\b|\bagency[- ]wide\b",
    re.IGNORECASE,
)


def wants_portfolio(text: str) -> bool:
    """Whether a message asks about the whole client portfolio. Pure.

    Conservative phrase gate — used to lift a web-chat turn out of its sticky
    single-client scope ('which clients need attention?' while scoped to Acme).
    A message that NAMES a client always wins over this (checked by callers)."""
    return bool(_PORTFOLIO_RE.search(text or ""))


def is_affirmative(text: str) -> bool:
    """Whether a reply confirms a pending action (a 'yes'). Pure."""
    t = (text or "").strip().lower().rstrip("!.")
    return t in {
        "yes", "y", "yep", "yeah", "yup", "confirm", "confirmed", "do it",
        "go", "go ahead", "proceed", "ok", "okay", "sure", "please do",
    } or t.startswith(("yes ", "yes,", "go ahead", "do it"))


# ---------------------------------------------------------------------------
# SOP grounding — strategy-shaped questions ALWAYS carry the agency SOPs
# (owner ruling, 2026-07-07). Two mechanisms, mirroring the strategist run:
# a deterministic keyword gate injects a budgeted `sop_library` selection into
# the prompt, and a `read_sop` tool lets the model pull any doc/section the
# gate didn't cover (bounded rounds). Both surfaces (Slack + dashboard chat)
# share this because both funnel through `interpret()`.
# ---------------------------------------------------------------------------

# Question shapes that must be SOP-grounded: strategy / changes of approach /
# forecasting / prioritization / budget / process ("how do we…"). Generous by
# design — a false positive costs prompt tokens, a false negative costs trust.
_SOP_HINT_RE = re.compile(
    r"strateg|forecast|project(?:ion|ed)?|trajector|"
    r"improve|recommend|priorit|focus|approach|tactic|"
    r"plan\b|planning|next step|what should|should we|what would|how do we|"
    r"how should|why (?:is|are|did|has|have)|"
    r"budget|allocat|retainer|spend|"
    r"drop|decline|recover|penalt|deindex|"
    r"link.?build|backlink|citation|review|gbp|"
    r"reoptimi|optimi[sz]e|on.?page|"
    r"ai visibility|ai overview|aio\b|aeo\b|"
    r"leadoff|market intel|market selection|market opportunit",
    re.IGNORECASE,
)

# Question keywords → sop_library relevance domains (see sop_library._RELEVANCE),
# joined with domains inferred from which modules are live in the context.
_SOP_DOMAIN_HINTS: list[tuple[str, str]] = [
    (r"maps|gbp|local pack|geo.?grid|review", "maps"),
    (r"ai visibility|ai overview|ai mode|aio\b|aeo\b|chatgpt|perplexity|gemini", "ai_visibility"),
    (r"link.?build|backlink|referring domain|citation|offpage|disavow", "offpage"),
    (r"budget|retainer|allocat|spend|task plan|recipe", "budget"),
    (r"content|blog|page|on.?page|silo|internal link|schema", "content"),
    (r"drop|decline|fell|lost rank|penalt|deindex|cannibal", "organic_drop"),
    (r"leadoff|market intel|market opportunit|market selection|effort target|which (?:city|market)", "leadoff"),
    # Ranking vocabulary itself — "how can we rank / get found / show up /
    # outrank X". Absent this, "how can <client> rank in <city>" resolved to no
    # domain at all and the block degraded to the router doc alone.
    (r"\brank(?:ing)?s?\b|\boutrank\b|\bget found\b|\bshow up\b|\bcompete\b|\bvisib(?:le|ility)\b", "content"),
    (r"\brank(?:ing)?s?\b|\bget found\b|\bshow up\b|\boutrank\b", "maps_growth"),
]


# The only turns that DON'T need the playbook: pure data reads ("what's our
# rank for X", "how many keywords", "when did the last scan run") and bare
# imperatives ("add an asana task for Ivy") — a stored number or a tool call is
# a complete answer, and a SOP adds nothing but tokens.
# Advisory language anywhere in the message overrides this (checked below), so
# "what's our rank for X and how do we improve it" still gets grounded.
_DATA_LOOKUP_RE = re.compile(
    r"^\s*(?:hi|hey|hello|thanks|thank you|ok(?:ay)?|got it|cool|nice)\b|"
    r"\bwhat(?:'?s| is| are)? (?:our|the|their) (?:rank|ranking|position|score|dr|"
    r"rd|traffic|clicks|impressions|visibility|average|status)\b|"
    r"\bwhat rank\b|\bwhere (?:do|are) we rank\b|"
    r"\bhow many\b|\bhow much (?:is|are|do we)\b|"
    r"\bwhen (?:did|was|is)\b|\bwho (?:is|are)\b|"
    r"\b(?:list|show me|give me)\b|\bdo we have\b|"
    # A bare command — the answer is the tool call, not advice.
    r"^\s*(?:add|remove|delete|create|run|push|generate|rebuild|scan|set|"
    r"update|complete|mark|assign|track|untrack|refresh|publish)\b",
    re.IGNORECASE,
)


def wants_sop_grounding(text: str) -> bool:
    """Whether this turn must carry the agency SOP library. Pure.

    **Inverted 2026-07-30 (owner ruling).** This was a keyword allowlist, and it
    silently missed "how can <client> rank in <city>" — a textbook Maps-SOP
    question that got answered with no playbook attached at all, in one pass,
    and read as generic. An allowlist can only ever cover the phrasings someone
    thought of; the next unanticipated one fails identically.

    So the default is now YES and only a pure data read opts out. A needless SOP
    block costs prompt tokens; a missing one costs a generic answer, which is
    the failure we're fixing — over-attaching is the cheaper mistake.
    """
    t = (text or "").strip()
    if not t:
        return False
    # An explicit strategy shape always grounds, even if phrased as a lookup
    # ("what's our rank for X and how do we improve it").
    if _SOP_HINT_RE.search(t):
        return True
    return not _DATA_LOOKUP_RE.search(t)


# ---------------------------------------------------------------------------
# Underspecified asks — make "ask when unsure" actually fire.
#
# The system prompt has always told SerMaStr to ask a clarifying question when
# a request is ambiguous, but that instruction sits mid-prompt and is pulled
# against by the Director's-voice block above it ("commit", "lead with the
# answer", "end with the ball in play") and hedged in its own paragraph ("don't
# over-ask"). Faced with a bare "what should we do?", the cheapest fully
# compliant output is a confident generic list — prompt-satisfying, useless.
#
# So the trigger is computed here instead of left to the model's judgement: when
# a turn asks for direction and nothing in the conversation says direction
# toward WHAT, `interpret` appends an explicit instruction for that turn only.
# Deliberately conservative — it fires only when there is no anchor anywhere in
# the message OR the recent history, since a vague follow-up in a conversation
# already about a keyword is not vague at all.
# ---------------------------------------------------------------------------

# Asking for direction ("what should we do?", "any ideas?", "where do we focus?").
_ADVICE_RE = re.compile(
    r"\bwhat (?:should|would|do|can|could) (?:we|i|you)\b|"
    r"\bwhat(?:'?s| is)? next\b|\bwhat now\b|\bwhere (?:to|do we go) (?:from here|next)\b|"
    r"\b(?:any )?(?:ideas|thoughts|suggestions?|recommendations?)\b|"
    r"\bwhat do you (?:think|reckon)\b|"
    r"\bhow (?:can|could|do|does|should|would)\b|\bwhere should we\b|"
    r"\bhelp (?:me|us)\b|\bfix (?:this|it)\b|\bmake it better\b",
    re.IGNORECASE,
)

# Something concrete for advice to attach to: a named module or metric, a
# timeframe, a quoted phrase, a URL, or any number. Broad on purpose — one
# anchor is enough to make an ask answerable, and a missed anchor costs an
# unnecessary question.
_ANCHOR_RE = re.compile(
    r"\bkeywords?\b|\bserp\b|"
    r"\bmaps?\b|\blocal pack\b|\bgeo.?grid\b|\bgbp\b|\bgoogle business\b|"
    r"\bai (?:visibility|overview|mode)\b|\baio\b|\baeo\b|\bchatgpt\b|"
    r"\bcontent\b|\bblog\b|\bsilo\b|\bschema\b|\bon.?page\b|"
    r"\blinks?\b|\bbacklinks?\b|\breferring domain\b|\bcitations?\b|\bauthority\b|"
    r"\breviews?\b|\bbudget\b|\bretainer\b|\bspend\b|\breports?\b|\bgoals?\b|"
    r"\bcompetitors?\b|\btraffic\b|\bclicks?\b|\bimpressions?\b|\bconversions?\b|"
    r"\bleads?\b|\brevenue\b|\bgsc\b|\bsearch console\b|\blocal seo\b|\becommerce\b|"
    r"\bproducts?\b|\bsyndication\b|\bfreeze\b|\bdeindex\b|\bdrops?\b|"
    r"\bthis (?:month|week|quarter|year)\b|\bnext (?:month|week|quarter|year)\b|"
    r"\bq[1-4]\b|\bby (?:friday|monday|end of)\b|"
    r"[\"“'‘][^\"”'’]{3,}[\"”'’]|"          # a quoted phrase — usually the keyword
    r"https?://|www\.|\b\w+\.(?:com|co|net|org|au|uk)\b|"
    r"\d",                                    # any number pins something
    re.IGNORECASE,
)

# Recent turns scanned for an anchor before calling a follow-up underspecified.
_ANCHOR_HISTORY_TURNS = 6


def _has_anchor(text: str, keywords: list[str]) -> bool:
    """Whether `text` names anything advice could attach to — a module, metric,
    timeframe, quoted phrase, URL, number, or one of the client's own tracked
    keywords. Pure."""
    if not text:
        return False
    if _ANCHOR_RE.search(text):
        return True
    low = text.lower()
    return any(k and k.lower() in low for k in keywords)


def _tracked_keywords(context: Optional[dict]) -> list[str]:
    """The client's tracked keyword strings from the assembled context, so a
    message naming one counts as anchored even with no other signal. Pure;
    tolerant of a missing/!empty organic_rank module."""
    rows = ((context or {}).get("organic_rank") or {}).get("keywords") or []
    return [str(r.get("keyword")) for r in rows if isinstance(r, dict) and r.get("keyword")]


def looks_underspecified(
    message: str,
    context: Optional[dict] = None,
    history: Optional[list[dict]] = None,
) -> bool:
    """True when a turn asks for direction but names nothing to direct at. Pure.

    Drives the per-turn clarify instruction in `interpret`. Requires ALL of:
    the message asks for advice; it carries no anchor; and no anchor appears in
    the recent conversation either — so "what should we do?" is flagged, while
    "what should we do about the maps drop?" and the same bare question asked
    three turns into a conversation about a keyword are not.
    """
    if not _ADVICE_RE.search(message or ""):
        return False
    keywords = _tracked_keywords(context)
    if _has_anchor(message, keywords):
        return False
    for turn in (history or [])[-_ANCHOR_HISTORY_TURNS:]:
        if _has_anchor((turn or {}).get("content") or "", keywords):
            return False
    return True


# ---------------------------------------------------------------------------
# Ranking-strategy asks — scope before strategising.
#
# "how can bsa claims rank in pompano beach" is the canonical case. It is a
# request for a whole campaign strategy, and it is missing the two things that
# decide what that strategy IS: which keyword (a roofer's "storm damage repair"
# and "roof replacement" want different pages, different links, different
# timelines), and which channel — the web SERP, the Maps local pack and AI
# answers are three different games with three different playbooks. Answering
# without them produces the generic checklist that reads as filler.
#
# The generic clarify gate above already catches this question, but its
# instruction is "ask ONE question", which is the wrong shape here: keyword and
# channel are orthogonal, both cheap to answer, and a strategy needs both. So a
# ranking-shaped ask gets its own per-turn instruction, and this gate wins over
# the generic one in `interpret` (more specific instruction, same mechanism).
#
# The gate is deliberately shape-only. WHICH of the two specifics is missing is
# left to the model — that is ordinary reading comprehension it does reliably,
# unlike remembering to ask at all, which is the thing that needed pinning down.
# ---------------------------------------------------------------------------

# Wanting to rank — as an aim, not as a metric being looked up.
_RANKING_INTENT_RE = re.compile(
    r"\brank(?:ing)? (?:in|for|at|on)\b|"
    r"\b(?:to|start|begin|get|be|become|keep) rank(?:ing)?\b|"
    r"\brank (?:higher|better|well|top|first|#?\d)\b|"
    r"\bshow up (?:in|for|on|when)\b|\bget (?:seen|found) (?:in|for|on)\b|"
    r"\bget (?:in|into) the (?:map ?pack|local pack|3.?pack|top)\b|"
    r"\bbreak into\b|\bcompete (?:in|for)\b|"
    r"\bimprove (?:our |the |their )?rank(?:ing)?s?\b|"
    r"\bvisibility (?:in|for)\b|\bdominate\b",
    re.IGNORECASE,
)

# Wanting it, phrased as a goal rather than as a question ("we want to rank in X").
_RANK_DESIRE_RE = re.compile(
    r"\b(?:want|need|trying|like|hoping|looking) to\b|\bgoal is\b|"
    r"\bhelp (?:us|me|them|him|her)\b|\bget (?:us|them|him|her)\b",
    re.IGNORECASE,
)


def looks_like_ranking_strategy_ask(message: str) -> bool:
    """True when a turn asks how to rank somewhere — a strategy request, not a
    metric lookup. Pure.

    Drives the scope-first instruction in `interpret`. Requires ranking INTENT
    (wanting to rank) plus either an advice shape ("how can we…") or a desire
    shape ("we want to…"), so "how can bsa claims rank in pompano beach" fires
    while "what's our rank in pompano" (a lookup) and "how did we rank last
    month" (past tense — no advice match) do not.

    Shape only: whether the message already names the keyword and channel is the
    model's read, instructed by the nudge. Firing on an already-scoped ask is
    harmless — the nudge tells it not to re-ask what it has.
    """
    text = message or ""
    if not _RANKING_INTENT_RE.search(text):
        return False
    return bool(_ADVICE_RE.search(text) or _RANK_DESIRE_RE.search(text))


def sop_domains(question: str, context: dict) -> set[str]:
    """The sop_library relevance domains for a question: keyword hints from the
    question itself plus what's live/alerting in the client context. Pure."""
    q = question or ""
    domains = {d for pat, d in _SOP_DOMAIN_HINTS if re.search(pat, q, re.IGNORECASE)}
    ctx = context or {}
    if (ctx.get("organic_rank") or {}).get("open_drop_alerts"):
        domains.add("organic_drop")
    # The "maps" domain leads with Rank_Drop_MITIGATION — a diagnostic doc. It
    # used to be added merely because the client HAS a geo-grid, which is true
    # of every local client, so a growth question ("how do we rank in Jupiter?")
    # spent 6.7k of a 24k budget on drop mitigation and starved the docs that
    # actually answered it. Gate it on a real drop, mirroring organic_drop.
    if (ctx.get("maps_geogrid") or {}).get("open_alerts"):
        domains.add("maps")
    if "ai_visibility" in ctx:
        domains.add("ai_visibility")
    # Never return empty on a grounded turn: with no domain at all the selection
    # collapses to the router doc, which is the thin-advice failure again. On-page
    # + architecture is the widest-applicable floor.
    return domains or {"content"}
