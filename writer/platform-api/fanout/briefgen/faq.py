"""Brief Generator Steps 10 + 10.5 — FAQ generation + intent gate (M13 slice 5c).

Builds a FAQ-question candidate pool (PAA + Reddit `?`-extraction + LLM concerns +
persona gaps), runs the v2.2 two-stage intent gate (cosine floor on a
`text-embedding-3-large` intent-profile, then an LLM intent-role classifier that drops
`different_audience` questions), scores (0.4 source / 0.4 semantic / 0.2 novelty) and
selects 3-5. The Writer (M14) writes the answers; the brief carries the questions.

Pure: extract_questions / source_signal / build_intent_profile / score_faq / select_faqs.
Egress: `generate_faqs` (one embed batch + one classifier call, both injected).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .entity import cosine

INTENT_FLOOR = 0.55      # Step 10.5 stage-1 cosine floor
FAQ_MIN_SCORE = 0.5      # Step 10 selection threshold
FAQ_MIN = 3
FAQ_MAX = 5

_Q_RE = re.compile(r"[^.!?\n]*\?")


@dataclass
class FaqCandidate:
    question: str
    source: str             # "paa" | "reddit" | "llm_concern" | "persona_gap"
    upvotes: int = 0


# ----- pure -----------------------------------------------------------------


def extract_questions(texts: list[str]) -> list[str]:
    """Sentences ending in '?' (Reddit titles/comments), 5-25 words (bundle Step 10 A)."""
    out: list[str] = []
    for t in texts or []:
        for m in _Q_RE.findall(t or ""):
            q = m.strip()
            if 5 <= len(q.split()) <= 25:
                out.append(q)
    return out


def source_signal(source: str, upvotes: int = 0) -> float:
    """Per-source signal (bundle Step 10 scoring formula)."""
    if source == "paa":
        return 1.0
    if source == "reddit":
        return 0.9 if upvotes >= 50 else 0.6 if upvotes >= 10 else 0.3
    if source == "llm_concern":
        return 0.5
    if source == "persona_gap":
        return 0.6
    return 0.3


def build_intent_profile(intent_type: str, title: str, scope_statement: str, primary_goal: str) -> str:
    return " ".join(p for p in (intent_type, title, scope_statement, primary_goal) if p).strip()


def score_faq(signal: float, semantic_relevance: float, novelty: float) -> float:
    return 0.4 * signal + 0.4 * semantic_relevance + 0.2 * novelty


@dataclass
class ScoredFaq:
    candidate: FaqCandidate
    score: float
    intent_role: str = "matches_primary_intent"


def select_faqs(
    scored: list[ScoredFaq], *, min_score: float = FAQ_MIN_SCORE, lo: int = FAQ_MIN, hi: int = FAQ_MAX,
) -> list[ScoredFaq]:
    """Top `hi` by score above `min_score`; if fewer than `lo` pass, accept the top `lo`
    regardless (always output lo-hi). `adjacent_intent` survivors are only used to top up
    when fewer than `lo` `matches_primary_intent` pass (bundle Step 10.5 relaxation)."""
    ranked = sorted(scored, key=lambda x: x.score, reverse=True)
    primary = [s for s in ranked if s.intent_role == "matches_primary_intent"]
    passing = [s for s in primary if s.score >= min_score]
    if len(passing) >= lo:
        return passing[:hi]                       # enough above threshold -> top `hi`
    # fewer than `lo` pass the threshold: accept the top `lo` regardless of threshold,
    # topping up primary with the best adjacent_intent survivors (honest shortfall if
    # fewer than `lo` candidates exist at all).
    adjacent = [s for s in ranked if s.intent_role == "adjacent_intent"]
    return (primary + adjacent)[:lo]


# ----- egress orchestration -------------------------------------------------


def generate_faqs(
    *, paa: list[str], discussions: list[dict], persona_gaps: list[dict],
    intent_type: str, title: str, scope_statement: str, primary_goal: str,
    heading_texts: list[str], embed_3large, classify_llm, concern_llm=None,
) -> tuple[list[dict], dict]:
    """Returns (selected FAQ dicts [{question, source}], gate metadata). Degrades to an
    empty list if there are no candidates."""
    cands: list[FaqCandidate] = []
    cands += [FaqCandidate(q, "paa") for q in paa if q]
    reddit_texts = [d.get("title") or "" for d in discussions] + [d.get("content") or "" for d in discussions]
    cands += [FaqCandidate(q, "reddit") for q in extract_questions(reddit_texts)]
    if concern_llm is not None and discussions:
        cands += [FaqCandidate(q, "llm_concern") for q in _extract_concerns(discussions, concern_llm)]
    cands += [FaqCandidate(g["question"], "persona_gap") for g in persona_gaps if g.get("question")]

    # dedup by question (case-insensitive), keep the strongest-signal source first.
    seen: dict[str, FaqCandidate] = {}
    for c in sorted(cands, key=lambda c: source_signal(c.source, c.upvotes), reverse=True):
        seen.setdefault(c.question.strip().lower(), c)
    cands = list(seen.values())
    meta = {"faq_candidate_count": len(cands), "faq_intent_gate_floor_rejected_count": 0}
    if not cands:
        return [], meta

    # Stage 1 — cosine floor (one embed batch: intent_profile + title + every question).
    intent_profile = build_intent_profile(intent_type, title, scope_statement, primary_goal)
    vecs = embed_3large([intent_profile, title, *[c.question for c in cands]])
    ip_vec, title_vec, q_vecs = vecs[0], vecs[1], vecs[2:]
    survivors: list[tuple[FaqCandidate, list[float]]] = []
    for c, qv in zip(cands, q_vecs):
        if cosine(qv, ip_vec) < INTENT_FLOOR:
            meta["faq_intent_gate_floor_rejected_count"] += 1
            continue
        survivors.append((c, qv))
    if not survivors:
        return [], meta

    # Stage 2 — LLM intent-role classifier (one batched call); drop different_audience.
    roles = _classify_intent_roles([c.question for c, _ in survivors], intent_type, title, classify_llm)

    heading_set = {h.strip().lower() for h in heading_texts}
    scored: list[ScoredFaq] = []
    for c, qv in survivors:
        role = roles.get(c.question, "matches_primary_intent")
        if role == "different_audience":
            continue
        sem = 0.5 * cosine(qv, title_vec) + 0.5 * cosine(qv, ip_vec)
        novelty = 1.0 if c.question.strip().lower() not in heading_set else 0.0
        scored.append(ScoredFaq(c, score_faq(source_signal(c.source, c.upvotes), sem, novelty), role))

    selected = select_faqs(scored)
    meta["faq_selected_count"] = len(selected)
    return [{"question": s.candidate.question, "source": s.candidate.source} for s in selected], meta


def _extract_concerns(discussions: list[dict], llm) -> list[str]:
    """Source B: up to 10 implicit questions/concerns from the Reddit thread content."""
    schema = {"type": "object",
              "properties": {"questions": {"type": "array", "items": {"type": "string"}}},
              "required": ["questions"]}
    blob = "\n\n".join((d.get("content") or d.get("title") or "")[:1500] for d in discussions)[:8000]
    if not blob.strip():
        return []
    try:
        out = llm.call_tool(
            system="Extract up to 10 implicit questions or concerns real users raise in these discussions.",
            user=blob, tool_name="extract_concerns",
            tool_description="Return implicit user questions.", input_schema=schema,
            purpose="brief_faq_concerns",
        )
    except Exception:  # noqa: BLE001 — optional source; degrade
        return []
    return [q.strip() for q in (out.get("questions") or []) if isinstance(q, str) and q.strip()][:10]


def _classify_intent_roles(questions: list[str], intent_type: str, title: str, llm) -> dict[str, str]:
    """Stage 2 batched classifier -> {question: intent_role}. On failure, treat all as
    matches_primary_intent (fail-open: the cosine floor already culled off-topic)."""
    schema = {
        "type": "object",
        "properties": {"verifications": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "intent_role": {"type": "string",
                                "enum": ["matches_primary_intent", "adjacent_intent", "different_audience"]},
            },
            "required": ["question", "intent_role"],
        }}},
        "required": ["verifications"],
    }
    listing = "\n".join(f"- {q}" for q in questions)
    try:
        out = llm.call_tool(
            system=(
                f"The article's primary intent is '{intent_type}' and its title is '{title}'. "
                "Classify each FAQ by whether it matches the PRIMARY reader's intent, is "
                "adjacent (on-topic but a different stakeholder), or targets a different "
                "audience entirely. Drop nothing — just label."
            ),
            user=listing, tool_name="classify_faq_intent",
            tool_description="Classify each FAQ's intent role.", input_schema=schema,
            purpose="brief_faq_intent_gate",
        )
    except Exception:  # noqa: BLE001 — fail-open
        return {q: "matches_primary_intent" for q in questions}
    return {
        (v.get("question") or "").strip(): v.get("intent_role", "matches_primary_intent")
        for v in (out.get("verifications") or []) if isinstance(v, dict)
    }
