"""AI-visibility capture — the report's LLM signal (report increment 3, outreach ISSUES I-095).

"When a customer asks an AI assistant for the best <keyword> in <region>, is this business named?"
Two engines (owner ruling 2026-08-08): **ChatGPT** (OpenAI) and **Google AI Overview** (AIO, via
DataForSEO). Runs per (ai_region, keyword) — the answer is the same for every prospect in the
region, so the per-prospect "is THIS business named" detection happens at report-read time
(platform-api), not here. That is what keeps it cheap: a handful of regions × keywords × 2 engines.

Reuses the proven pieces rather than re-deriving them: the OpenAI call + tolerant name parser from
`ai_granularity.py` (the I-004 spike), and the DataForSEO auth + live-endpoint shape from
`organic_scan.py`. BILLS (OpenAI per ChatGPT call, one DataForSEO request per AIO call) and is
gated like every paid command; writes `cost_ledger` rows.

**Three-way outcome, never collapsed** (the `ai_granularity.py` discipline): an engine that NAMED
NOBODY, an engine that FAILED, and an engine that named businesses are three different facts. A
failure raises out of the engine call and is recorded as `present=False` with the error, never as
"the AI doesn't know you" — an outage must not manufacture invisibility, which is the strongest
pitch in the market.

**AIO shape is MEASURED on first run** (the `dataforseo_client.py` lesson): `parse_aio` is tolerant
of the ai_overview envelope and `capture_aio` logs one full sample, because nothing here has parsed
an AI Overview against this account before.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..config import Settings
from .ai_granularity import (
    AiGranularityError,
    ask_engine,
    build_prompt,
    missing_openai_vars,
    parse_business_names,
)
from .organic_scan import ORGANIC_LIVE_PATH, domain_of
from .scan_runner import BASE_URL, _auth_header

logger = logging.getLogger(__name__)

ENGINE_CHATGPT = "chatgpt"
ENGINE_AIO = "google_aio"

_TASK_STATUS_OK = 20000
_US_LOCATION_CODE = 2840
_RAW_EXCERPT_CHARS = 2000


@dataclass
class EngineAnswer:
    """One engine's answer for one region × keyword, ready to store. Not the prospect verdict —
    that is computed later against a specific business."""

    engine: str
    present: bool
    named_businesses: list[str] = field(default_factory=list)
    reference_domains: list[str] = field(default_factory=list)
    raw_excerpt: str = ""
    error: str = ""


@dataclass
class AiScanReport:
    ai_region: str = ""
    keyword: str = ""
    engines: list[EngineAnswer] = field(default_factory=list)
    stored: int = 0
    problems: list[str] = field(default_factory=list)


# --- ChatGPT engine ---------------------------------------------------------------------------


async def ask_chatgpt(
    settings: Settings, keyword: str, region: str, model: str
) -> EngineAnswer:
    """Ask ChatGPT the consumer question and parse the businesses it names.

    Reuses `ai_granularity.build_prompt` verbatim so the AI-visibility question is worded exactly
    like the spike's — one definition of "the consumer question". A failed call is recorded, not
    raised, so one dead engine doesn't lose the other."""
    try:
        raw = await ask_engine(settings.openai_api_key, model, build_prompt(keyword, region))
    except AiGranularityError as exc:
        return EngineAnswer(engine=ENGINE_CHATGPT, present=False, error=str(exc))
    names = list(parse_business_names(raw))
    return EngineAnswer(
        engine=ENGINE_CHATGPT,
        present=bool(names),
        named_businesses=names,
        raw_excerpt=raw[:_RAW_EXCERPT_CHARS],
    )


# --- AIO engine (Google AI Overview via DataForSEO) -------------------------------------------


def build_aio_task(keyword: str, region: str, *, language_code: str, device: str) -> dict[str, Any]:
    """A DataForSEO organic request for the consumer question, worded to elicit an AI Overview.

    Uses a TEXT query ("best <keyword> in <region>") + a US location_code rather than the
    coordinate anchor the organic-rank capture uses: AIO is about recognition of a named place, not
    a proximity-ranked local pack, so the place goes in the query where the model reads it."""
    return {
        "keyword": f"best {keyword} in {region}",
        "location_code": _US_LOCATION_CODE,
        "language_code": language_code,
        "device": device,
        "depth": 10,
    }


def parse_aio(body: dict[str, Any]) -> EngineAnswer:
    """Read the ai_overview element out of an organic response. Tolerant; RAISES on task error.

    The AIO's cited sources are the "named businesses" here: their titles feed name matching and
    their domains feed domain matching. Concatenated item text is kept as the excerpt so a business
    named in prose but not cited is still detectable. Absent ai_overview element → present=False
    (the model showed no AI answer for this query), which is a finding, not a failure."""
    tasks = body.get("tasks") or []
    if not tasks:
        raise AiGranularityError("aio response carried no tasks")
    task = tasks[0] or {}
    status = task.get("status_code")
    if status is not None and status != _TASK_STATUS_OK:
        raise AiGranularityError(
            f"aio task failed: status_code={status} message={task.get('status_message')!r}"
        )
    result = task.get("result") or []
    items = (result[0] or {}).get("items") if result else None
    if not isinstance(items, list):
        items = []

    aio = next((i for i in items if isinstance(i, dict) and i.get("type") == "ai_overview"), None)
    if not aio:
        return EngineAnswer(engine=ENGINE_AIO, present=False)

    references = aio.get("references")
    if not isinstance(references, list):
        references = []
    titles: list[str] = []
    domains: list[str] = []
    for ref in references:
        if not isinstance(ref, dict):
            continue
        title = str(ref.get("title") or "").strip()
        if title:
            titles.append(title)
        dom = domain_of(ref.get("domain") or ref.get("url"))
        if dom:
            domains.append(dom)

    # Concatenate any nested text the AIO carries, for the raw excerpt (name-in-prose detection).
    texts: list[str] = []
    for sub in (aio.get("items") or []):
        if isinstance(sub, dict) and sub.get("text"):
            texts.append(str(sub["text"]))
    if aio.get("text"):
        texts.insert(0, str(aio["text"]))

    return EngineAnswer(
        engine=ENGINE_AIO,
        present=True,
        named_businesses=titles,
        reference_domains=sorted(set(domains)),
        raw_excerpt=" ".join(texts)[:_RAW_EXCERPT_CHARS],
    )


async def capture_aio(
    settings: Settings,
    keyword: str,
    region: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> EngineAnswer:
    """One DataForSEO organic call for the AIO consumer question. BILLS one request."""
    task = build_aio_task(
        keyword, region,
        language_code=settings.dataforseo_default_language_code,
        device=settings.scan_device,
    )
    owns = client is None
    client = client or httpx.AsyncClient(timeout=settings.dataforseo_request_timeout_seconds)
    try:
        response = await client.post(
            f"{BASE_URL}{ORGANIC_LIVE_PATH}", headers=_auth_header(settings), json=[task]
        )
        response.raise_for_status()
        body = response.json()
    finally:
        if owns:
            await client.aclose()
    logger.info("aio sample", extra={"raw": str(body)[:4000]})
    try:
        return parse_aio(body)
    except AiGranularityError as exc:
        return EngineAnswer(engine=ENGINE_AIO, present=False, error=str(exc))


# --- the scan ---------------------------------------------------------------------------------


async def run_ai_scan(
    db: Any,
    settings: Settings,
    ai_region: dict[str, Any],
    keyword: dict[str, Any],
    *,
    engines: "tuple[str, ...]" = (ENGINE_CHATGPT, ENGINE_AIO),
    market_id: str | None = None,
) -> AiScanReport:
    """Ask the chosen engines about one region × keyword and store one row per engine. BILLS.

    Best-effort per engine: a failure is stored as `present=False` (with the error visible) rather
    than aborting the other engine, and a `cost_ledger` row is written best-effort per engine that
    actually made a call."""
    region_name = str(ai_region.get("name") or "")
    term = str(keyword.get("term") or "")
    report = AiScanReport(ai_region=region_name, keyword=term)

    for engine in engines:
        if engine == ENGINE_CHATGPT:
            missing = missing_openai_vars(settings)
            if missing:
                report.problems.append(f"chatgpt skipped — missing {', '.join(missing)}")
                continue
            answer = await ask_chatgpt(settings, term, region_name, settings.ai_visibility_chatgpt_model)
            cost_cents = settings.ai_visibility_openai_cost_cents
            stage = "b3_ai_chatgpt"
        elif engine == ENGINE_AIO:
            from .dataforseo_client import missing_dataforseo_vars

            missing = missing_dataforseo_vars(settings)
            if missing:
                report.problems.append(f"aio skipped — missing {', '.join(missing)}")
                continue
            answer = await capture_aio(settings, term, region_name)
            cost_cents = settings.dataforseo_cost_per_request_cents
            stage = "b3_ai_aio"
        else:
            report.problems.append(f"unknown engine {engine!r}")
            continue

        report.engines.append(answer)
        db.table("ai_scan_result").insert(
            {
                "ai_region_id": ai_region["id"],
                "keyword_id": keyword["id"],
                "engine": engine,
                "present": answer.present,
                "named_businesses": answer.named_businesses,
                "reference_domains": answer.reference_domains,
                "raw_excerpt": answer.raw_excerpt or None,
            }
        ).execute()
        report.stored += 1

        try:
            from .cost import build_ledger_row

            db.table("cost_ledger").insert(
                build_ledger_row(
                    market_id=market_id, cycle_number=None, stage=stage,
                    provider=("openai" if engine == ENGINE_CHATGPT else "dataforseo"),
                    units=1, cost_cents=cost_cents,
                )
            ).execute()
        except Exception as exc:  # noqa: BLE001 — a ledger failure must never cost the capture
            logger.error("could not write cost_ledger row", extra={"error": str(exc)[:500]})

    logger.info(
        "ai visibility scan complete",
        extra={"region": region_name, "keyword": term, "stored": report.stored},
    )
    return report
