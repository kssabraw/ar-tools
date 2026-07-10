"""OpenAI wrapper for silo discovery (PRD §7.1, Appendix B.1).

- Grounding pass: GPT-5.4 with web search reads top content for the bare seed,
  reports subject category + dominant audience, and judges ambiguity.
- Silo proposal: GPT-5.4 with web search proposes silos as strict JSON.
- Embeddings: text-embedding-3-small for the per-silo relevance anchor.

Every model call emits an `llm_call` structured log (PRD §16.3).
"""

import json
import logging
import random
import re
import time

from openai import OpenAI

from fanout.cancellation import raise_if_cancelled
from fanout.cost_meter import llm_token_cost, record_cost
from fanout.llm.embeddings import EmbeddingError, OpenAIEmbedder
from fanout.pipeline.models import (
    PROPOSABLE_TYPES,
    GroundingResult,
    ProposedSilo,
    RelationshipType,
)

logger = logging.getLogger(__name__)


class LLMError(Exception):
    pass


# Transport-retry parity with the Anthropic client (fanout/llm/anthropic_client
# .py::_is_retryable): 429 rate limit, timeouts, connection drops, and 5xx are
# transient — previously any OpenAI 429 raised LLMError immediately, aborting
# silo grounding/proposal outright.
_MAX_TRANSPORT_ATTEMPTS = 4


def _is_retryable(exc: Exception) -> bool:
    import openai

    if isinstance(exc, (openai.RateLimitError, openai.APITimeoutError, openai.APIConnectionError)):
        return True
    if isinstance(exc, openai.APIStatusError):
        return exc.status_code == 429 or exc.status_code >= 500
    return False


def _extract_json(text: str):
    """Parse JSON from a model response, tolerating prose or code fences."""
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Fall back to the first {...} or [...] span.
        for opener, closer in (("{", "}"), ("[", "]")):
            start, end = text.find(opener), text.rfind(closer)
            if start != -1 and end > start:
                try:
                    return json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    continue
    raise LLMError("Model did not return valid JSON")


class OpenAILLM:
    def __init__(
        self,
        api_key: str,
        silo_model: str,
        embedding_model: str,
        web_search_tool: str = "web_search",
        embedder=None,
    ):
        self._client = OpenAI(api_key=api_key)
        self._silo_model = silo_model
        self._embedding_model = embedding_model
        self._web_search_tool = web_search_tool
        # Embedding backend is provider-pluggable (locked-decision override
        # 2026-06-15: OpenAI -> Gemini). Defaults to OpenAI on this client's own
        # embedding model so existing callers/tests are unchanged.
        self._embedder = embedder or OpenAIEmbedder(self._client, embedding_model)

    def _respond(self, prompt: str, purpose: str, *, browsing: bool) -> str:
        raise_if_cancelled()
        started = time.perf_counter()
        kwargs: dict = {"model": self._silo_model, "input": prompt}
        if browsing:
            kwargs["tools"] = [{"type": self._web_search_tool}]
        resp = None
        for attempt in range(_MAX_TRANSPORT_ATTEMPTS):
            raise_if_cancelled()
            try:
                resp = self._client.responses.create(**kwargs)
                break
            except Exception as exc:  # noqa: BLE001 — surfaced as LLMError to caller
                # Mirror the Anthropic client: exponential backoff + jitter on
                # transient transport errors (1.5s/3s/6s, capped at 8s).
                if _is_retryable(exc) and attempt < _MAX_TRANSPORT_ATTEMPTS - 1:
                    time.sleep(min(8.0, 1.5 * (2 ** attempt)) + random.uniform(0, 0.5))
                    continue
                raise LLMError(f"OpenAI call failed ({purpose}): {exc}") from exc
        latency_ms = round((time.perf_counter() - started) * 1000, 2)

        usage = getattr(resp, "usage", None)
        input_tokens = getattr(usage, "input_tokens", None)
        output_tokens = getattr(usage, "output_tokens", None)
        cost = llm_token_cost(self._silo_model, input_tokens, output_tokens)
        record_cost(cost)  # PRD §16.4 — token-derived cost
        logger.info(
            "llm_call",
            extra={
                "event": "llm_call",
                "purpose": purpose,
                "provider": "openai",
                "model": self._silo_model,
                "prompt_tokens": input_tokens,
                "completion_tokens": output_tokens,
                "latency_ms": latency_ms,
                "cost_usd": cost,
                "status": "success",
            },
        )
        text = getattr(resp, "output_text", None)
        if not text:
            raise LLMError(f"Empty model response ({purpose})")
        return text

    def ground_subject(self, seed: str, disambiguation_hint: str | None) -> GroundingResult:
        hint_line = (
            f"The user clarified the intended meaning: {disambiguation_hint}\n"
            if disambiguation_hint
            else ""
        )
        prompt = (
            f"Research the topic '{seed}' using web search and summarize what it is.\n"
            f"{hint_line}"
            "Return ONLY a JSON object with keys:\n"
            '  "summary": ~400 word plain-text overview of the subject,\n'
            '  "subject_category": short category label (e.g. drug, product, concept, location),\n'
            '  "detected_audience": the dominant audience for top-ranking content,\n'
            '  "is_ambiguous": true if the seed clearly refers to two or more disjoint subjects '
            "(e.g. a planet AND a chemical element), otherwise false,\n"
            '  "interpretations": when ambiguous, a list of short distinct interpretation labels; else [],\n'
            '  "aliases": common nicknames/abbreviations/spellings for THIS subject '
            '(e.g. "reta" for retatrutide); [] if none,\n'
            '  "peer_entities": other named entities in the SAME category that are NOT this '
            "subject — competitors or siblings someone researching this subject would confuse it "
            '(e.g. for retatrutide: tirzepatide, semaglutide, ozempic; for an iPhone: Galaxy, Pixel). '
            "Names only, no generic words. [] if none.\n"
        )
        data = _extract_json(self._respond(prompt, "subject_grounding", browsing=True))
        # A supplied disambiguation hint resolves ambiguity outright (PRD §7.1.2).
        is_ambiguous = bool(data.get("is_ambiguous")) and not disambiguation_hint
        return GroundingResult(
            summary=str(data.get("summary", "")),
            subject_category=data.get("subject_category"),
            detected_audience=data.get("detected_audience"),
            is_ambiguous=is_ambiguous,
            interpretations=[str(i) for i in (data.get("interpretations") or [])],
            aliases=[str(a).strip() for a in (data.get("aliases") or []) if str(a).strip()],
            peer_entities=[str(p).strip() for p in (data.get("peer_entities") or []) if str(p).strip()],
        )

    def propose_silos(
        self,
        seed: str,
        topic_count: int,
        audience: str | None,
        grounding_summary: str,
        demand_keywords: list[str],
        competitor_paths: list[str],
    ) -> list[ProposedSilo]:
        prompt = self._silo_prompt(
            seed, topic_count, audience, grounding_summary, demand_keywords, competitor_paths
        )
        # One reprompt if the first attempt yields no valid on-taxonomy silos
        # (PRD §5.2: off-taxonomy returns are reprompted, max two attempts).
        last_error: str | None = None
        for attempt in range(2):
            text = self._respond(
                prompt
                if last_error is None
                else f"{prompt}\n\nYour previous response was rejected: {last_error}\n"
                "Return a corrected strict JSON array.",
                "silo_proposal",
                browsing=True,
            )
            try:
                raw = _extract_json(text)
            except LLMError as exc:
                last_error = str(exc)
                continue
            silos = self._parse_silos(raw)
            if silos:
                return silos
            last_error = "No valid, on-taxonomy silos were returned."
        return []

    def silo_anchor_examples(
        self,
        *,
        seed: str,
        silo_name: str,
        rationale: str,
        relationship_type: str,
        peer_terms: list[str],
        n: int = 30,
    ) -> list[str]:
        """LLM-generate ~N example keywords that exemplify a silo's coverage,
        for the enriched silo anchor (routing calibration). The centroid of
        these examples' embeddings is more discriminative than the rationale
        embedding alone (which is seed-dominated). Strict peer-entity exclusion
        so the anchor doesn't pull in keywords the §7.6 filter will then drop."""
        peer_clause = (
            "NEVER include any of these peer entities (they belong to other "
            f"subjects, not this silo): {', '.join(peer_terms)}.\n"
            if peer_terms else ""
        )
        prompt = (
            f"You are populating the keyword anchor for ONE silo on a niche "
            f"authority site about \"{seed}\".\n\n"
            f"SILO: {silo_name}\n"
            f"What this silo covers: {rationale}\n"
            f"Relationship type: {relationship_type}\n\n"
            f"Generate {n} example keywords a researcher might search that would "
            f"belong in THIS silo. They should illustrate the breadth of what "
            f"this silo covers — not paraphrase each other.\n\n"
            "RULES:\n"
            f"1. Every example must be relevant to someone researching {seed}.\n"
            f"2. {peer_clause}"
            f"3. Mix of informational, transactional, and question-style queries.\n"
            "4. 2-8 words each. No URLs, no proper nouns of peer entities.\n"
            "5. Do not repeat the silo name verbatim.\n\n"
            f"Return ONLY a strict JSON array of {n} strings."
        )
        # The grounding-style models are fine for this; no browsing needed.
        text = self._respond(prompt, "silo_anchor_examples", browsing=False)
        try:
            raw = _extract_json(text)
        except LLMError:
            return []
        if not isinstance(raw, list):
            return []
        out: list[str] = []
        seen: set[str] = set()
        for item in raw:
            if not isinstance(item, str):
                continue
            kw = item.strip().lower()
            if 2 <= len(kw.split()) <= 12 and kw not in seen:
                seen.add(kw)
                out.append(kw)
        return out

    def route_ambiguous_keywords(
        self,
        *,
        seed: str,
        silos: list[dict],
        keywords: list[str],
    ) -> dict[str, str]:
        """Pick the best-fitting silo id for each keyword (batched). Returns
        only mappings the model produced — caller decides what to do with
        keywords the model didn't route. Returns {} on parse failure."""
        if not keywords or not silos:
            return {}
        silos_block = "\n".join(
            f"- [id={s['id']}] {s.get('name') or ''}: {s.get('rationale') or ''}"
            for s in silos
        )
        kw_block = "\n".join(f"{i+1}. {kw}" for i, kw in enumerate(keywords))
        prompt = (
            f"You are routing keywords to silos on a niche authority site "
            f"about \"{seed}\".\n\n"
            f"AVAILABLE SILOS:\n{silos_block}\n\n"
            "For each keyword, decide which silo it best belongs to. Pick by the "
            "keyword's PRIMARY INTENT, not just shared tokens. A keyword that "
            "names a peer entity (a different drug / product / brand from the "
            "seed) usually belongs in a mechanism / comparison silo, not in a "
            "results / dosage one.\n\n"
            f"KEYWORDS:\n{kw_block}\n\n"
            'Return ONLY a strict JSON array of {"keyword": "<exact text>", '
            '"silo_id": "<the id>"} objects. Length must equal the number of '
            "keywords. Do not paraphrase the keyword text."
        )
        text = self._respond(prompt, "route_ambiguous_keywords", browsing=False)
        try:
            raw = _extract_json(text)
        except LLMError:
            return {}
        if not isinstance(raw, list):
            return {}
        valid_silo_ids = {s["id"] for s in silos}
        out: dict[str, str] = {}
        for item in raw:
            if not isinstance(item, dict):
                continue
            kw = item.get("keyword")
            sid = item.get("silo_id")
            if isinstance(kw, str) and isinstance(sid, str) and sid in valid_silo_ids:
                out[kw] = sid
        return out

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Delegate to the configured embedding backend (OpenAI or Gemini),
        preserving the historical ``LLMError`` contract for callers."""
        try:
            return self._embedder.embed(texts)
        except EmbeddingError as exc:
            raise LLMError(str(exc)) from exc

    @staticmethod
    def _parse_silos(raw) -> list[ProposedSilo]:
        if isinstance(raw, dict):
            raw = raw.get("silos") or raw.get("topics") or []
        if not isinstance(raw, list):
            return []
        silos: list[ProposedSilo] = []
        for item in raw:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            try:
                rel = RelationshipType(item.get("relationship_type"))
            except ValueError:
                continue  # off-taxonomy — drop (PRD §5.2)
            if rel not in PROPOSABLE_TYPES:
                continue  # peer_entity filtered before display (PRD §5.1)
            silos.append(
                ProposedSilo(
                    name=str(item["name"]).strip(),
                    rationale=str(item.get("rationale", "")).strip(),
                    relationship_type=rel,
                    supporting_evidence=(
                        str(item["supporting_evidence"]).strip()
                        if item.get("supporting_evidence")
                        else None
                    ),
                    is_broader_class=bool(item.get("is_broader_class"))
                    or rel is RelationshipType.broader_class,
                )
            )
        return silos

    @staticmethod
    def _silo_prompt(
        seed: str,
        topic_count: int,
        audience: str | None,
        grounding_summary: str,
        demand_keywords: list[str],
        competitor_paths: list[str],
    ) -> str:
        demand = "\n".join(f"- {k}" for k in demand_keywords[:30]) or "- (none available)"
        paths = "\n".join(f"- {p}" for p in competitor_paths) or "- (none available)"
        audience_line = audience or "(infer from the grounding summary)"
        return f"""You are proposing the top-level subfolder structure for a niche authority site about {seed}.

The site will be dedicated entirely to {seed}. Every article on it must serve someone researching, evaluating, or using {seed}.

AUDIENCE: {audience_line}

EVIDENCE GATHERED:
Subject grounding summary:
{grounding_summary}

Top keywords from the demand sample:
{demand}

Top competitor URL path patterns:
{paths}

YOUR JOB:
Propose {topic_count} subfolders ("silos") that together cover what this site needs to demonstrate topical authority. Each silo becomes a top-level section of the site with multiple articles inside it.

RULES:
1. Every silo must be tagged with one of these relationship_types:
   - property_or_mechanism: something {seed} IS or DOES
   - use_case: an application or scenario where {seed} is used
   - effect_or_outcome: what happens as a result of {seed}
   - practical_commercial: how someone obtains, uses, or operationalizes {seed}
   - research_or_trial: scientific evidence about {seed}
   - broader_class: a category that contains {seed} (use SPARINGLY; justify why a {seed} site needs this category-level coverage)
2. NEVER propose a peer entity as a silo. Peer entities are other things in the same category as {seed} (e.g. competing drugs, competing products, sibling concepts). They dilute topical authority.
3. Every silo must cite specific evidence in `supporting_evidence` — a keyword cluster from the demand sample, a competitor URL pattern, or an explicit reference to a fact from the grounding.

OUTPUT FORMAT:
Return ONLY a strict JSON array of {topic_count} objects:
[
  {{
    "name": "short name, 2-5 words",
    "rationale": "2-3 sentences on why this silo is essential for topical authority",
    "relationship_type": "one of the enums above",
    "supporting_evidence": "specific evidence from the materials provided",
    "is_broader_class": false
  }}
]"""
