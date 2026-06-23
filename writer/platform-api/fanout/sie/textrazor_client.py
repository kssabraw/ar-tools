"""SIE Module 11 pass-1: grounded NER via TextRazor (new service, key provisioned
2026-06-15; owner swap from Google NLP 2026-06-12 — PRD's grounded-NER design
preserved, Google-specific params mapped to TextRazor, §9 #6).

TextRazor grounds entities in actual page text (the model cannot invent — it
surfaces what's present), matching the PRD's "LLM pass-2 may not add" constraint.
Google's `salience ≥ 0.40` originally mapped to TextRazor `relevanceScore ≥ 0.40`,
but the relevance floor is now lenient (default 0.15, configurable) because there is
no page-spread gate here and the LLM pass-2 (`categorize_entities`) is the quality
backstop that drops off-topic / navigational entities. The 100 KB Google input cap is
kept as a truncation rule (TextRazor accepts more, so it's non-binding). The key is
sent as `x-textrazor-key` (header).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_MAX_BYTES = 100_000  # PRD truncation rule (Google NLP limit), kept for TextRazor.


@dataclass
class NerEntity:
    name: str            # matched surface text
    types: list[str]     # DBpedia/Freebase type strings (entity-type whitelist input)
    salience: float      # relevanceScore (Google-salience proxy)
    mentions: int


class TextRazorError(Exception):
    pass


class TextRazorClient:
    def __init__(
        self, api_key: str, base_url: str, *, cost_per_request: float = 0.0006,
        relevance_min: float = 0.40, timeout_s: float = 30.0, max_attempts: int = 3,
    ):
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._cost = cost_per_request
        self._relevance_min = relevance_min
        self._timeout = timeout_s
        self._max_attempts = max(1, max_attempts)

    def extract_entities(self, text: str) -> list[NerEntity]:
        """One document per request (PRD). Returns entities with relevanceScore ≥
        the threshold, deduped by matched text with summed mentions. Returns [] on
        failure (logged) so the per-page entity pass degrades gracefully."""
        import httpx  # lazy: keeps NerEntity importable (for entities.py) without httpx

        from fanout.cancellation import raise_if_cancelled
        from fanout.cost_meter import record_cost

        raise_if_cancelled()
        body = (text or "").encode("utf-8")[:_MAX_BYTES].decode("utf-8", "ignore")
        if not body.strip():
            return []
        started = time.perf_counter()
        for attempt in range(self._max_attempts):
            try:
                resp = httpx.post(
                    self._base_url,
                    headers={"x-textrazor-key": self._api_key},
                    data={"extractors": "entities", "text": body},
                    timeout=self._timeout,
                )
                if resp.status_code >= 400:
                    # 401/4xx here is concurrency/rate rejection (the key is valid),
                    # so back off before retrying to let contention clear.
                    if attempt < self._max_attempts - 1:
                        time.sleep(0.5 * (attempt + 1))
                    continue
                payload = resp.json()
                record_cost(self._cost)
                self._log(resp.status_code, started, "success")
                return self._parse(payload)
            except (httpx.HTTPError, ValueError):
                continue
        self._log(None, started, "failed")
        return []

    def _parse(self, payload: dict) -> list[NerEntity]:
        raw = (payload.get("response") or {}).get("entities") or []
        by_name: dict[str, NerEntity] = {}
        for ent in raw:
            score = float(ent.get("relevanceScore") or 0.0)
            if score < self._relevance_min:
                continue
            name = (ent.get("matchedText") or ent.get("entityId") or "").strip()
            if not name:
                continue
            key = name.lower()
            existing = by_name.get(key)
            if existing:
                existing.mentions += 1
                existing.salience = max(existing.salience, score)
            else:
                by_name[key] = NerEntity(
                    name=name, types=list(ent.get("type") or ent.get("dbpediaType") or []),
                    salience=score, mentions=1,
                )
        return list(by_name.values())

    def _log(self, status: int | None, started: float, outcome: str) -> None:
        logger.info(
            "external_call",
            extra={
                "event": "external_call", "service": "textrazor", "endpoint": "/",
                "status": status, "outcome": outcome,
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                "cost_usd": self._cost if outcome == "success" else 0.0,
            },
        )
