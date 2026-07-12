"""AI-lane pilot probe (validation, NOT a feature build) — app-run.

Gates four candidate LeadOff features (scanner CLAUDE.md "Idea bank → AI-lane")
by sampling DataForSEO's newer AI endpoints on known test markets:

  A) AIO citations — serp/google/organic/live/advanced with
     load_async_ai_overview=true (2× cost; without it async AIOs read back as
     null — a false-zero trap) on the 4 money-trade test markets (expected: no
     AIO, confirming the lane) + 4 known-AIO cells from market_scanner.
     aio_presence, so references[] actually populates. Citations classified
     directory vs local-site.
  B) LLM recommendations ("the AI pack") — ai_optimization/{chat_gpt,gemini,
     perplexity}/llm_responses/live, "best [service] in [city]" on the 4 test
     markets; keeps money_spent/tokens per call for real Pass-2 pricing.
  C) AI demand volume — ai_optimization/ai_keyword_data/keywords_search_volume
     /live; also tests whether a location is accepted (docs ambiguous — a
     rejection is itself a probe finding). ⚠ volumes are PAA-derived (modeled).

Discipline: every DataForSEO response envelope carries `cost` — accumulated
into a running tally, hard-stopped at PROBE_HARD_CAP; task-level status codes
checked (40203 money limit aborts, envelope 20000 ≠ task success); one spend
row recorded to leadoff_spend (action='ai_probe') with the ACTUAL total.
Results (per-section summaries + clipped raw samples) land on
async_jobs.result. One-off by design: enqueued directly (no HTTP route, no UI).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from db.supabase_client import get_supabase
from services.leadoff_actions import (
    _CODE_MONEY_LIMIT,
    _CODE_NO_RESULTS,
    _CODE_OK,
    _dfs_get,
    _dfs_post,
    _task0,
)

logger = logging.getLogger(__name__)

PROBE_HARD_CAP = 5.0

# The 4 requested test markets (money trades — the lane we sell into).
MARKETS = [
    ("plumber", "La Jolla, San Diego, CA", "32.8328,-117.2713"),
    ("locksmith", "La Jolla, San Diego, CA", "32.8328,-117.2713"),
    ("landscape architect", "La Jolla, San Diego, CA", "32.8328,-117.2713"),
    ("locksmith", "Kansas City, MO", "39.0997,-94.5786"),
]
# Known-AIO cells from market_scanner.aio_presence (so section A captures
# real references[] instead of eight ai_overview:null rows).
AIO_LIKELY = [
    ("arborist and tree surgeon", "Kansas City, MO", "39.0997,-94.5786"),
    ("arborist and tree surgeon", "San Diego, CA", "32.7157,-117.1611"),
    ("antenna service", "Frisco, TX", "33.1507,-96.8236"),
    ("stair contractor", "Cleveland, OH", "41.4993,-81.6944"),
]
DIRECTORIES = {"yelp.com", "angi.com", "thumbtack.com", "homeadvisor.com",
               "bbb.org", "yellowpages.com", "houzz.com", "expertise.com",
               "reddit.com", "quora.com", "wikipedia.org", "nextdoor.com",
               "porch.com", "bark.com", "care.com"}
# Cheap current-generation defaults; the job reads each engine's models list
# first and falls back to the first listed model if a pick is rejected.
MODEL_PICKS = {"chat_gpt": "gpt-4.1-mini", "gemini": "gemini-2.5-flash",
               "perplexity": "sonar"}


class _Tally:
    """Envelope-cost accumulator with the hard cap."""

    def __init__(self, cap: float) -> None:
        self.cap = cap
        self.spent = 0.0
        self.lines: list[str] = []

    def pay(self, envelope: dict, label: str) -> dict:
        cost = float(envelope.get("cost") or 0)
        self.spent = round(self.spent + cost, 4)
        self.lines.append(f"{label}: ${cost:.4f} (total ${self.spent:.4f})")
        if self.spent > self.cap:
            raise RuntimeError(f"probe_hard_cap_reached:{self.spent:.4f}")
        return envelope


def classify_domain(url: str | None) -> tuple[str | None, str]:
    """(domain, 'directory'|'local_site') for a citation URL. Pure."""
    d = (urlparse(url or "").netloc or "").lower()
    d = d[4:] if d.startswith("www.") else d
    if not d:
        return None, "local_site"
    return d, ("directory" if d in DIRECTORIES else "local_site")


def summarize_aio(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Presence + citation breakdown from a SERP items array. Pure."""
    aio = next((it for it in items if it.get("type") == "ai_overview"), None)
    if not aio:
        return {"aio": False}
    refs = aio.get("references") or []
    doms = [classify_domain(r.get("url")) for r in refs]
    return {
        "aio": True,
        "citations": len(refs),
        "directories": sorted({d for d, k in doms if d and k == "directory"}),
        "local_sites": sorted({d for d, k in doms if d and k == "local_site"}),
        "has_open_citation_slot": all(k == "directory" for d, k in doms if d),
    }


def clip(obj: Any, limit: int = 4000) -> Any:
    """Clip a raw sample for storage on the job row. Pure."""
    import json
    s = json.dumps(obj, default=str)
    return json.loads(s) if len(s) <= limit else s[:limit] + "…[clipped]"


async def _probe_aio(client: httpx.AsyncClient, tally: _Tally) -> dict[str, Any]:
    rows, raw_sample = [], None
    for i, (cat, place, coord) in enumerate(MARKETS + AIO_LIKELY):
        kw = f"{cat} near me"
        env = tally.pay(await _dfs_post(
            client, "/serp/google/organic/live/advanced",
            [{"keyword": kw, "location_coordinate": f"{coord},13z",
              "language_code": "en", "device": "desktop",
              "load_async_ai_overview": True, "depth": 10}]),
            f"serp {cat} @ {place.split(',')[0]}")
        t = _task0(env)
        if t.get("status_code") == _CODE_MONEY_LIMIT:
            raise RuntimeError("dataforseo_daily_limit")
        if t.get("status_code") == _CODE_NO_RESULTS:
            rows.append({"q": kw, "place": place, "aio": False, "note": "valid zero"})
            continue
        if t.get("status_code") != _CODE_OK:
            rows.append({"q": kw, "place": place, "error": t.get("status_message")})
            continue
        items = ((t.get("result") or [{}])[0] or {}).get("items") or []
        summary = summarize_aio(items)
        if summary["aio"] and raw_sample is None:
            raw_sample = clip(next(it for it in items
                                   if it.get("type") == "ai_overview"), 6000)
        rows.append({"q": kw, "place": place, **summary})
    return {"rows": rows, "raw_sample": raw_sample}


async def _probe_llm(client: httpx.AsyncClient, tally: _Tally) -> dict[str, Any]:
    models: dict[str, Any] = {}
    for eng in MODEL_PICKS:
        try:
            env = tally.pay(await _dfs_get(
                client, f"/ai_optimization/{eng}/llm_responses/models"),
                f"{eng} models list")
            t = _task0(env)
            listed = [m.get("model_name") for m in (t.get("result") or [])
                      if isinstance(m, dict) and m.get("model_name")]
            models[eng] = listed[:10]
        except Exception as exc:
            models[eng] = f"list_failed: {exc}"

    rows, raw_sample = [], None
    for cat, place, _ in MARKETS:
        for eng, pick in MODEL_PICKS.items():
            listed = models.get(eng) or []
            model = pick if (isinstance(listed, list) and pick in listed) \
                else (listed[0] if isinstance(listed, list) and listed else pick)
            payload: dict[str, Any] = {
                "user_prompt": (f"Who are the best {cat}s in {place}? "
                                "Name specific businesses."),
                "model_name": model, "max_output_tokens": 700,
            }
            if eng != "perplexity":
                payload["web_search"] = True
            try:
                env = tally.pay(await _dfs_post(
                    client, f"/ai_optimization/{eng}/llm_responses/live",
                    [payload]), f"{eng} {cat} @ {place.split(',')[0]}")
                t = _task0(env)
                if t.get("status_code") == _CODE_MONEY_LIMIT:
                    raise RuntimeError("dataforseo_daily_limit")
                if t.get("status_code") != _CODE_OK:
                    rows.append({"engine": eng, "market": f"{cat} @ {place}",
                                 "model": model,
                                 "error": t.get("status_message")})
                    continue
                res = ((t.get("result") or [{}])[0] or {})
                if raw_sample is None:
                    raw_sample = clip(res, 6000)
                text = " ".join(
                    str(sec.get("text") or "")
                    for it in (res.get("items") or [])
                    for sec in (it.get("sections") or [it]) if isinstance(sec, dict))
                rows.append({"engine": eng, "market": f"{cat} @ {place}",
                             "model": model,
                             "llm_money_spent": res.get("money_spent"),
                             "input_tokens": res.get("input_tokens"),
                             "output_tokens": res.get("output_tokens"),
                             "answer_head": text[:600]})
            except RuntimeError:
                raise
            except Exception as exc:
                rows.append({"engine": eng, "market": f"{cat} @ {place}",
                             "model": model, "error": str(exc)})
    return {"models": models, "rows": rows, "raw_sample": raw_sample}


async def _probe_volume(client: httpx.AsyncClient, tally: _Tally) -> dict[str, Any]:
    kws = sorted({c for c, _, _ in MARKETS}) + \
        [f"{c} near me" for c, _, _ in MARKETS[:2]]
    out: dict[str, Any] = {}
    for label, extra in (
        ("national", {}),
        ("us_location_code", {"location_code": 2840}),
        ("city_location_name",
         {"location_name": "San Diego,California,United States"}),
    ):
        try:
            env = tally.pay(await _dfs_post(
                client,
                "/ai_optimization/ai_keyword_data/keywords_search_volume/live",
                [{"keywords": kws, **extra}]), f"ai volume ({label})")
            t = _task0(env)
            if t.get("status_code") == _CODE_MONEY_LIMIT:
                raise RuntimeError("dataforseo_daily_limit")
            if t.get("status_code") != _CODE_OK:
                out[label] = {"rejected": t.get("status_message"),
                              "status_code": t.get("status_code")}
                continue
            items = ((t.get("result") or [{}])[0] or {}).get("items") or []
            out[label] = [{"keyword": it.get("keyword"),
                           "ai_search_volume": it.get("ai_search_volume"),
                           "trend_months": len(it.get("ai_monthly_searches")
                                               or [])} for it in items]
        except RuntimeError:
            raise
        except Exception as exc:
            out[label] = {"error": str(exc)}
    return out


async def run_ai_probe_job(job: dict) -> None:
    supabase = get_supabase()
    job_id = job["id"]
    payload = job.get("payload") or {}
    cap = min(float(payload.get("cap") or PROBE_HARD_CAP), PROBE_HARD_CAP)
    tally = _Tally(cap)
    result: dict[str, Any] = {"started_at": datetime.now(timezone.utc).isoformat()}
    try:
        async with httpx.AsyncClient() as client:
            result["aio_citations"] = await _probe_aio(client, tally)
            result["llm_recommendations"] = await _probe_llm(client, tally)
            result["ai_volume"] = await _probe_volume(client, tally)
        status = "complete"
    except Exception as exc:
        result["aborted"] = str(exc)[:300]
        status = "complete" if tally.lines else "failed"
        logger.error("leadoff_ai_probe.aborted",
                     extra={"job_id": job_id, "error": str(exc)})
    result["spend_lines"] = tally.lines
    result["total_spent_usd"] = tally.spent
    # one honest ledger row with the ACTUAL total (not an estimate)
    try:
        if payload.get("user_id") and tally.spent > 0:
            supabase.table("leadoff_spend").insert({
                "user_id": payload["user_id"], "action": "ai_probe",
                "est_cost": tally.spent}).execute()
    except Exception:
        logger.warning("leadoff_ai_probe.spend_record_failed",
                       extra={"job_id": job_id})
    supabase.table("async_jobs").update({
        "status": status, "result": result, "completed_at": "now()",
        **({} if status == "complete" else
           {"error": result.get("aborted", "probe_failed")}),
    }).eq("id", job_id).execute()
    logger.info("leadoff_ai_probe.done", extra={
        "job_id": job_id, "status": status, "spent": tally.spent})
