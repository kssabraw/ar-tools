"""DataForSEO client — the slices needed for silo discovery (PRD §7.1.1).

M2 uses two endpoints:
- Labs `keyword_ideas` for the ~200-row demand sample on the bare seed.
- SERP `organic` to read the top domains' URL path patterns.

Failures raise DataForSEOError; the silo-discovery orchestrator decides whether
that degrades the run (demand/competitor signal optional) or halts it.
"""

import logging
import time
from urllib.parse import urlparse

import httpx

from fanout.cancellation import raise_if_cancelled
from fanout.cost_meter import record_cost

logger = logging.getLogger(__name__)

# Default locale = US English. Per-country locale (E1, 2026-06-17): the client is
# now constructed with a session's location_code so the international client's
# research runs in their market. DataForSEO localizes by location_code; the
# language stays "en" for every supported English market (US/UK/CA/AU/NZ).
_LOCATION_CODE = 2840
_LANGUAGE_CODE = "en"


def _coerce_int(v) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _coerce_float(v) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


class DataForSEOError(Exception):
    pass


class DataForSEOClient:
    def __init__(
        self,
        base_url: str,
        login: str,
        password: str,
        location_code: int = _LOCATION_CODE,
        language_code: str = _LANGUAGE_CODE,
    ):
        self._base_url = base_url.rstrip("/")
        self._auth = (login, password)
        self._location_code = location_code
        self._language_code = language_code

    def _post(self, path: str, payload: list[dict]) -> dict:
        # Cooperative cancellation: a /cancel request signalled while the worker
        # is between calls aborts the run here, before paying for another one.
        raise_if_cancelled()
        url = f"{self._base_url}{path}"
        started = time.perf_counter()
        try:
            resp = httpx.post(url, json=payload, auth=self._auth, timeout=60.0)
        except httpx.HTTPError as exc:
            raise DataForSEOError(f"DataForSEO request failed: {exc}") from exc
        latency_ms = round((time.perf_counter() - started) * 1000, 2)

        if resp.status_code >= 400:
            raise DataForSEOError(f"DataForSEO {resp.status_code} for {path}")

        try:
            body = resp.json()
        except ValueError as exc:
            # A 200 with a non-JSON body (HTML error/maintenance page, gateway
            # interstitial). Treat as a DataForSEO failure so callers can degrade.
            raise DataForSEOError(f"DataForSEO returned non-JSON for {path}") from exc
        task = (body.get("tasks") or [{}])[0]
        cost = task.get("cost")
        record_cost(cost)  # PRD §16.4 — DataForSEO returns a real per-call cost
        logger.info(
            "external_call",
            extra={
                "event": "external_call",
                "service": "dataforseo",
                "endpoint": path,
                "latency_ms": latency_ms,
                "cost_usd": cost,
            },
        )
        if task.get("status_code", 0) >= 40000:
            raise DataForSEOError(
                f"DataForSEO task error {task.get('status_code')}: {task.get('status_message')}"
            )
        return task

    def keyword_ideas_sample(self, seed: str, limit: int = 200) -> list[str]:
        """~200 demand-sample keywords for the bare seed (no expansion)."""
        task = self._post(
            "/v3/dataforseo_labs/google/keyword_ideas/live",
            [
                {
                    "keywords": [seed],
                    "location_code": self._location_code,
                    "language_code": self._language_code,
                    "limit": limit,
                }
            ],
        )
        items = (task.get("result") or [{}])[0].get("items") or []
        keywords: list[str] = []
        for item in items:
            kw = item.get("keyword")
            if kw:
                keywords.append(kw)
        return keywords

    # ----- M3 expansion endpoints (PRD §7.3 / §7.5) -----------------------
    @staticmethod
    def _extract_labs_keywords(task: dict) -> list[str]:
        """Pull keyword strings from a Labs result, tolerating shape variance
        (`items[].keyword` or `items[].keyword_data.keyword`)."""
        items = (task.get("result") or [{}])[0].get("items") or []
        out: list[str] = []
        for item in items:
            kw = item.get("keyword")
            if not kw and isinstance(item.get("keyword_data"), dict):
                kw = item["keyword_data"].get("keyword")
            if kw:
                out.append(kw)
        return out

    def keyword_ideas(self, anchor: str, limit: int = 1000) -> list[str]:
        task = self._post(
            "/v3/dataforseo_labs/google/keyword_ideas/live",
            [{"keywords": [anchor], "location_code": self._location_code,
              "language_code": self._language_code, "limit": limit}],
        )
        return self._extract_labs_keywords(task)

    def keyword_suggestions(self, anchor: str, limit: int = 500) -> list[str]:
        task = self._post(
            "/v3/dataforseo_labs/google/keyword_suggestions/live",
            [{"keyword": anchor, "location_code": self._location_code,
              "language_code": self._language_code, "limit": limit}],
        )
        return self._extract_labs_keywords(task)

    def query_fanouts(self, anchor: str, limit: int = 300) -> list[str]:
        # Long-tail variations via DataForSEO Labs `related_keywords`. Each item
        # carries a node keyword (keyword_data.keyword) AND a related_keywords[]
        # array of strings — harvest both (the array is the bulk of the fan-out).
        task = self._post(
            "/v3/dataforseo_labs/google/related_keywords/live",
            [{"keyword": anchor, "location_code": self._location_code,
              "language_code": self._language_code, "depth": 2, "limit": limit}],
        )
        items = (task.get("result") or [{}])[0].get("items") or []
        out: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            kd = item.get("keyword_data") or {}
            if isinstance(kd, dict) and kd.get("keyword"):
                out.append(kd["keyword"])
            for rk in item.get("related_keywords") or []:
                if rk:
                    out.append(rk)
        return out

    def people_also_ask(self, anchor: str) -> list[str]:
        """PAA questions from the SERP for `anchor` (one tier)."""
        task = self._post(
            "/v3/serp/google/organic/live/advanced",
            [{"keyword": anchor, "location_code": self._location_code,
              "language_code": self._language_code, "depth": 20,
              "people_also_ask_click_depth": 1}],
        )
        items = (task.get("result") or [{}])[0].get("items") or []
        questions: list[str] = []
        for item in items:
            if item.get("type") != "people_also_ask":
                continue
            for q in item.get("items") or []:
                title = q.get("title")
                if title:
                    questions.append(title)
        return questions

    def autocomplete(self, keyword: str) -> list[str]:
        task = self._post(
            "/v3/serp/google/autocomplete/live/advanced",
            [{"keyword": keyword, "location_code": self._location_code,
              "language_code": self._language_code}],
        )
        items = (task.get("result") or [{}])[0].get("items") or []
        out: list[str] = []
        for item in items:
            sug = item.get("suggestion") or item.get("keyword")
            if sug:
                out.append(sug)
        return out

    # ----- M4 competitor mining (PRD §7.4) --------------------------------
    def serp_top_urls(self, keyword: str, top_n: int = 5) -> list[str]:
        """Top organic result URLs (full URLs) for `keyword`, for competitor
        mining. `top_n` is 5 in standard mode, 10 in comprehensive (§7.4)."""
        task = self._post(
            "/v3/serp/google/organic/live/advanced",
            [{"keyword": keyword, "location_code": self._location_code,
              "language_code": self._language_code, "depth": max(top_n, 10)}],
        )
        items = (task.get("result") or [{}])[0].get("items") or []
        urls: list[str] = []
        for item in items:
            if item.get("type") != "organic":
                continue
            url = item.get("url")
            if url:
                urls.append(url)
            if len(urls) >= top_n:
                break
        return urls

    def serp_top_results(self, keyword: str, depth: int = 20) -> list[dict]:
        """SIE M2: top-`depth` organic results WITH metadata (url/title/description/
        rank/type). `serp_top_urls` drops the metadata SIE needs for M3 classification."""
        task = self._post(
            "/v3/serp/google/organic/live/advanced",
            [{"keyword": keyword, "location_code": self._location_code,
              "language_code": self._language_code, "depth": depth}],
        )
        items = (task.get("result") or [{}])[0].get("items") or []
        out: list[dict] = []
        for item in items:
            if item.get("type") != "organic":
                continue
            url = item.get("url")
            if not url:
                continue
            out.append({
                "url": url,
                "title": item.get("title"),
                "description": item.get("description"),
                "rank": _coerce_int(item.get("rank_absolute")) or len(out) + 1,
                "type": item.get("type"),
            })
            if len(out) >= depth:
                break
        return out

    def ranked_keywords(
        self, target_domain: str, limit: int = 500, max_position: int = 20
    ) -> list[str]:
        """Keywords `target_domain` ranks for in organic positions 1..max_position
        (DataForSEO Labs `ranked_keywords`, PRD §7.4). The DataForSEO target is a
        domain; results are filtered to the requested rank ceiling server-side."""
        task = self._post(
            "/v3/dataforseo_labs/google/ranked_keywords/live",
            [{"target": target_domain, "location_code": self._location_code,
              "language_code": self._language_code, "limit": limit,
              "filters": [
                  ["ranked_serp_element.serp_item.rank_absolute", "<=", max_position]
              ]}],
        )
        items = (task.get("result") or [{}])[0].get("items") or []
        out: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            kd = item.get("keyword_data") or {}
            kw = kd.get("keyword") if isinstance(kd, dict) else None
            if kw:
                out.append(kw)
        return out

    def keyword_overview(self, keywords: list[str]) -> dict[str, dict]:
        """Per-keyword metrics for a batch (PRD §7.8): search volume, CPC,
        keyword difficulty, competition index. Returns a {keyword: {volume,
        cpc_usd, keyword_difficulty, competition_index}} map. DataForSEO Labs
        `keyword_overview` accepts up to 700 keywords per task — the caller
        is responsible for batching at or below that limit. Missing keywords
        (no data) are simply absent from the returned map; the cost meter
        picks up the per-call charge from `task["cost"]`."""
        if not keywords:
            return {}
        task = self._post(
            "/v3/dataforseo_labs/google/keyword_overview/live",
            [{"keywords": list(keywords), "location_code": self._location_code,
              "language_code": self._language_code}],
        )
        items = (task.get("result") or [{}])[0].get("items") or []
        out: dict[str, dict] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            kw = item.get("keyword")
            if not isinstance(kw, str):
                continue
            ki = item.get("keyword_info") or {}
            kp = item.get("keyword_properties") or {}
            si = item.get("search_intent_info") or {}
            row = {
                "volume": _coerce_int(ki.get("search_volume")),
                "cpc_usd": _coerce_float(ki.get("cpc")),
                "competition_index": _coerce_float(ki.get("competition_index")),
                # KD lives under keyword_properties on Labs; fall back to None
                # so a missing field doesn't drop the whole row.
                "keyword_difficulty": _coerce_float(
                    kp.get("keyword_difficulty") if isinstance(kp, dict) else None
                ),
                "search_intent": (
                    si.get("main_intent") if isinstance(si, dict) else None
                ),
            }
            out[kw] = row
        return out

    @staticmethod
    def domain_of(url: str) -> str | None:
        """Bare registrable host for a URL (drops scheme, path, leading www.)."""
        host = urlparse(url).netloc.lower()
        if not host:
            return None
        if host.startswith("www."):
            host = host[4:]
        return host or None

    def serp_competitor_paths(self, seed: str, top_n: int = 5) -> list[str]:
        """URL path patterns from the top organic domains for the seed."""
        task = self._post(
            "/v3/serp/google/organic/live/advanced",
            [
                {
                    "keyword": seed,
                    "location_code": self._location_code,
                    "language_code": self._language_code,
                    "depth": max(top_n, 10),
                }
            ],
        )
        items = (task.get("result") or [{}])[0].get("items") or []
        paths: list[str] = []
        for item in items:
            if item.get("type") != "organic":
                continue
            url = item.get("url")
            if not url:
                continue
            path = urlparse(url).path.strip("/")
            if path:
                paths.append(path)
            if len(paths) >= top_n:
                break
        return paths

    # ----- M13 Brief Generator sources (Steps 1-2) ------------------------
    # Thin egress: these return the RAW DataForSEO items[]; the brief module's
    # pure parsers (app/briefgen/sources.py) shape them, so the parsing is
    # unit-testable without egress. Reddit + LLM-Responses + the AIO block are
    # docs-derived shapes — confirm on the first deployed brief run.

    def serp_advanced_items(
        self, keyword: str, depth: int = 20, *, load_async_aio: bool = True
    ) -> list[dict]:
        """Brief Gen Step 1 (+ X.1 AIO capture) + Step 2A PAA + Step 2B discussion
        threads in ONE SERP-advanced call (efficiency E2/E3): returns the raw items[]
        (organic + ai_overview + people_also_ask + discussions_and_forums).
        `load_async_aio` adds `load_async_ai_overview` to capture async AIOs too
        (+$0.0006, refunded if absent/cached; aio-optimization-plan.md §5.6)."""
        payload = {
            "keyword": keyword, "location_code": self._location_code,
            "language_code": self._language_code, "depth": depth,
            "people_also_ask_click_depth": 1,
        }
        if load_async_aio:
            payload["load_async_ai_overview"] = True
        task = self._post("/v3/serp/google/organic/live/advanced", [payload])
        return (task.get("result") or [{}])[0].get("items") or []

    def llm_response_items(
        self, prompt: str, provider: str, model_name: str | None = None
    ) -> list[dict]:
        """Brief Gen Step 2D (one LLM's answer): DataForSEO AI Optimization "LLM
        Responses". `provider` ∈ {`chat_gpt`, `gemini`} (E4 trims Claude + Perplexity).
        `model_name` is REQUIRED by the endpoint (omitting it -> 40501 "Invalid Field:
        'model_name'"); defaults to the per-provider config value. Returns raw items[]."""
        if model_name is None:
            from fanout.config import get_settings
            model_name = get_settings().brief_llm_response_models.get(provider)
        payload = {
            "user_prompt": prompt, "location_code": self._location_code,
            "language_code": self._language_code, "web_search": True,
        }
        if model_name:
            payload["model_name"] = model_name
        task = self._post(
            f"/v3/ai_optimization/{provider}/llm_responses/live", [payload]
        )
        return (task.get("result") or [{}])[0].get("items") or []
