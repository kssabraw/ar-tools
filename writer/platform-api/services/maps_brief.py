"""Local-pack collapse brief — the proactive reasoning folded into a maps-drop
alert.

When a scheduled geo-grid scan opens a *critical* batch of alerts (a lost_pack
collapse), the notification the team receives used to be a terse pointer — "N
local-pack alerts detected" + a link — leaving the actual reasoning (which
competitor surged, which quadrants were lost, the single highest-leverage move)
inside a weekly strategist review nobody was pushed to open.

This module turns that alert batch into a short "why + top move" brief and hands
it back to ``maps_analyzer.analyze_scan`` as the notification *summary*, so the
reasoning rides the existing notification path into BOTH Slack and the in-app
feed with no new surface.

Design:
- **Deterministic grounding.** The brief is built from the alert facts the
  analyzer already computed (competitor names, compass quadrants, from→to
  deltas) — never invented. ``alert_facts`` renders those facts; the LLM's job
  is to synthesise, not to source numbers.
- **One small best-effort call** via ``report_llm`` (provider-selectable, with
  cross-provider fallback), on the maps_report provider (OpenAI by default — a
  separate quota from the Anthropic account the per-keyword reports saturate).
- **Never blocks or breaks the analyze job.** Disabled, keyless, empty, or
  errored → ``None`` → the caller keeps the deterministic digest summary.

The pure helpers (``alert_facts``, ``build_brief_prompt``) are unit-tested; the
one impure entrypoint (``generate_brief``) isolates the DB read + LLM call.
"""

from __future__ import annotations

import logging
from typing import Optional, Sequence

from config import settings

logger = logging.getLogger(__name__)


_SYSTEM = (
    "You are SerMaStr, a local-SEO strategist writing a proactive alert for the "
    "agency team about a Google Maps (local pack) ranking collapse for one client.\n\n"
    "You are given the DETERMINISTIC facts of what changed this scan — the "
    "keywords affected, which competitors surged and by how many grid pins, and "
    "which compass sectors (N/NE/E/…) weakened. These facts are measured; treat "
    "them as ground truth and NEVER invent a competitor, number, sector, or "
    "cause that is not in them.\n\n"
    "Write a tight brief (3–4 sentences, no headers, no bullet list, plain prose) "
    "that a busy owner can act on:\n"
    "1. WHAT collapsed — lead with the keyword(s) and the scale of the drop.\n"
    "2. WHY, as far as the facts show — name the specific competitor(s) that "
    "surged and the sector(s) that weakened. If the facts don't identify a "
    "cause, say the drop is broad rather than guessing one.\n"
    "3. The single highest-leverage MOVE, grounded in local-pack levers only: "
    "GBP review volume/velocity, GBP posts, a location/service page targeting a "
    "weak sector, or citation consistency. Name ONE move and the sector/keyword "
    "it targets — do not list options.\n\n"
    "Be concrete and specific to these facts. No preamble, no sign-off, no "
    "'here is your brief'. Do not fabricate metrics."
)


def alert_facts(opened_alerts: Sequence[dict]) -> str:
    """Render the opened-alert batch as a deterministic fact list for the prompt.

    Uses each alert's own human message (already carries competitor names,
    sectors, and from→to deltas), de-duplicated and order-preserving. Pure."""
    lines: list[str] = []
    seen: set[str] = set()
    for a in opened_alerts:
        msg = (a.get("message") or "").strip()
        if msg and msg not in seen:
            seen.add(msg)
            lines.append(f"- {msg}")
    return "\n".join(lines)


def build_brief_prompt(client_name: str, opened_alerts: Sequence[dict]) -> tuple[str, str]:
    """The (system, user) prompt for the collapse brief. Pure — unit-tested."""
    facts = alert_facts(opened_alerts)
    user = (
        f"Client: {client_name or 'this client'}\n\n"
        f"What changed this scan (measured facts — the ONLY numbers you may cite):\n"
        f"{facts or '- (no per-alert detail available)'}\n\n"
        f"Write the brief."
    )
    return _SYSTEM, user


def generate_brief(client_name: str, opened_alerts: Sequence[dict]) -> Optional[str]:
    """Generate the collapse brief, or None to fall back to the terse digest.

    Best-effort: gated off, no facts, no LLM key, or any error → None. Runs
    synchronously (the caller is threaded off the event loop) via the shared
    provider-fallback transport."""
    if not settings.maps_brief_enabled:
        return None
    if not opened_alerts or not alert_facts(opened_alerts):
        return None
    system, user = build_brief_prompt(client_name, opened_alerts)
    try:
        from services import report_llm

        text = report_llm.generate_text_sync(
            system=system,
            user=user,
            provider=settings.maps_brief_provider,
            model=settings.maps_brief_model,
            max_tokens=settings.maps_brief_max_tokens,
            log_tag="maps_brief",
        )
    except Exception as exc:  # best-effort — never break the analyze job
        logger.warning("maps_brief_failed", extra={"error": str(exc)})
        return None
    text = (text or "").strip()
    return text or None
