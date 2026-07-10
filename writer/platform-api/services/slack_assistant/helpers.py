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
    r"ai visibility|ai overview|aio\b|aeo\b",
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
]


def wants_sop_grounding(text: str) -> bool:
    """True when the message is strategy-shaped and must carry the SOPs. Pure."""
    return bool(_SOP_HINT_RE.search(text or ""))


def sop_domains(question: str, context: dict) -> set[str]:
    """The sop_library relevance domains for a question: keyword hints from the
    question itself plus what's live/alerting in the client context. Pure."""
    q = question or ""
    domains = {d for pat, d in _SOP_DOMAIN_HINTS if re.search(pat, q, re.IGNORECASE)}
    ctx = context or {}
    if (ctx.get("organic_rank") or {}).get("open_drop_alerts"):
        domains.add("organic_drop")
    if "maps_geogrid" in ctx:
        domains.add("maps")
    if "ai_visibility" in ctx:
        domains.add("ai_visibility")
    return domains
