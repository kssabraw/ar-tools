#!/usr/bin/env python3
"""Recommend new cosine thresholds after the Gemini embedding switch.

Every gate threshold is a decision boundary on a cosine distribution. Switching
to gemini-embedding-2 shifts that distribution (it runs lower + spreads wider
than OpenAI/embedding-001), so the old constants no longer mean the same thing
and must be re-derived — not hand-guessed.

This calibrates against the suite's OWN labeled history. Persisted briefs record
both the headings that PASSED each gate (`output_payload.heading_structure`) and
those DISCARDED, each tagged with a `discard_reason`
(`below_relevance_floor`, `region_restates_title`, `above_restatement_ceiling`,
`scope_verification_out_of_scope`, ...). We re-embed both groups with
gemini-embedding-2 and find the threshold that best reproduces the old pass/
discard decisions in the NEW space. Silo dedup is calibrated from the cross-silo
(same-client) negative distribution.

Needs ONLY GEMINI_API_KEY + the DB (NOT OpenAI — it uses labels, not old
cosines), so it can run at pre-cutover or after the OpenAI teardown.

Run from writer/platform-api with the platform env loaded:

    python -m scripts.calibrate_embedding_thresholds
    python -m scripts.calibrate_embedding_thresholds --gate relevance_floor
    python -m scripts.calibrate_embedding_thresholds --model gemini-embedding-2 --json out.json

Each gate prints: N positives/negatives, the cosine distributions, the current
config value, and a RECOMMENDED value with the policy used. Nothing is written to
config — you review the numbers and set them (then shadow-run a few briefs).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from statistics import mean

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings                        # noqa: E402
from db.supabase_client import get_supabase         # noqa: E402

_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
_BATCH = 100


# --------------------------------------------------------------------------- #
# Embedding (gemini-embedding-2, cached by text)
# --------------------------------------------------------------------------- #

def _make_embedder(model: str, dim: int, api_key: str):
    cache: dict[str, list[float]] = {}
    url = f"{_GEMINI_BASE}/models/{model}:batchEmbedContents"

    def embed(texts: list[str]) -> dict[str, list[float]]:
        todo = sorted({t for t in texts if t and t not in cache})
        for i in range(0, len(todo), _BATCH):
            chunk = todo[i:i + _BATCH]
            payload = {"requests": [
                {"model": f"models/{model}", "content": {"parts": [{"text": t}]},
                 "taskType": "SEMANTIC_SIMILARITY", "outputDimensionality": dim}
                for t in chunk
            ]}
            r = httpx.post(url, headers={"x-goog-api-key": api_key}, json=payload, timeout=60.0)
            r.raise_for_status()
            embs = r.json().get("embeddings") or []
            if len(embs) != len(chunk):
                raise RuntimeError(f"embed count mismatch {len(embs)}!={len(chunk)}")
            for t, e in zip(chunk, embs):
                cache[t] = [float(x) for x in (e.get("values") or [])]
        return {t: cache[t] for t in texts if t in cache}

    return embed


def _cos(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def _pct(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    k = max(0, min(len(s) - 1, int(round(p / 100.0 * (len(s) - 1)))))
    return s[k]


def _summary(xs: list[float]) -> str:
    if not xs:
        return "n=0"
    return (f"n={len(xs)} min={min(xs):.3f} p10={_pct(xs,10):.3f} "
            f"med={_pct(xs,50):.3f} mean={mean(xs):.3f} p90={_pct(xs,90):.3f} max={max(xs):.3f}")


# --------------------------------------------------------------------------- #
# Data loading
# --------------------------------------------------------------------------- #

def _load_briefs(limit: int) -> list[dict]:
    q = (get_supabase().table("module_outputs")
         .select("output_payload").eq("module", "brief"))
    if limit:
        q = q.limit(limit)
    rows = q.execute().data or []
    out = []
    for r in rows:
        p = r.get("output_payload") or {}
        if isinstance(p, str):
            try:
                p = json.loads(p)
            except Exception:
                continue
        if p.get("keyword"):
            out.append(p)
    return out


def _headings(p: dict) -> list[str]:
    hs = p.get("heading_structure") or []
    return [(h.get("text") or "").strip() for h in hs
            if isinstance(h, dict) and (h.get("text") or "").strip()
            and (h.get("level") in (2, 3, "h2", "h3", None))]


def _discarded(p: dict, reasons: set[str]) -> list[str]:
    dh = p.get("discarded_headings") or []
    return [(d.get("text") or "").strip() for d in dh
            if isinstance(d, dict) and (d.get("discard_reason") in reasons)
            and (d.get("text") or "").strip()]


# --------------------------------------------------------------------------- #
# Threshold policies
# --------------------------------------------------------------------------- #

def _best_floor(pos: list[float], neg: list[float]) -> dict:
    """A FLOOR admits positives (score >= floor), rejects negatives. Report the
    Youden-J-optimal cut and a conservative one that keeps 95% of positives."""
    cands = sorted(set(pos + neg))
    best_j, best_t = -2.0, 0.0
    for t in cands:
        tpr = sum(1 for x in pos if x >= t) / len(pos) if pos else 0.0
        fpr = sum(1 for x in neg if x >= t) / len(neg) if neg else 0.0
        if tpr - fpr > best_j:
            best_j, best_t = tpr - fpr, t
    keep95 = _pct(pos, 5)  # floor that retains ~95% of positives
    return {
        "recommended": round(best_t, 3), "policy": "Youden-J (max TPR-FPR)",
        "conservative_keep95pos": round(keep95, 3),
        "at_recommended": {
            "positives_kept": round(sum(1 for x in pos if x >= best_t) / len(pos), 3) if pos else None,
            "negatives_rejected": round(sum(1 for x in neg if x < best_t) / len(neg), 3) if neg else None,
        },
    }


def _best_ceiling(keep: list[float], drop: list[float]) -> dict:
    """A CEILING rejects too-similar items (score >= ceiling -> drop). `drop` are
    the too-similar negatives, `keep` the retained. Report Youden-J + a
    conservative cut that rejects 95% of the drop group."""
    cands = sorted(set(keep + drop))
    best_j, best_t = -2.0, 1.0
    for t in cands:
        tnr = sum(1 for x in drop if x >= t) / len(drop) if drop else 0.0   # correctly dropped
        fpr = sum(1 for x in keep if x >= t) / len(keep) if keep else 0.0   # wrongly dropped
        if tnr - fpr > best_j:
            best_j, best_t = tnr - fpr, t
    reject95 = _pct(drop, 5)  # ceiling that catches ~95% of restatements
    return {
        "recommended": round(best_t, 3), "policy": "Youden-J (max drop-hit - false-drop)",
        "conservative_catch95drop": round(reject95, 3),
        "at_recommended": {
            "restatements_caught": round(sum(1 for x in drop if x >= best_t) / len(drop), 3) if drop else None,
            "kept_survive": round(sum(1 for x in keep if x < best_t) / len(keep), 3) if keep else None,
        },
    }


# --------------------------------------------------------------------------- #
# Gates
# --------------------------------------------------------------------------- #

def calibrate_relevance_floor(briefs, embed) -> dict:
    pos_pairs, neg_pairs, texts = [], [], set()
    for p in briefs:
        kw = p["keyword"].strip()
        texts.add(kw)
        for h in _headings(p):
            pos_pairs.append((h, kw)); texts.add(h)
        for h in _discarded(p, {"below_relevance_floor", "h3_below_parent_relevance_floor"}):
            neg_pairs.append((h, kw)); texts.add(h)
    vecs = embed(sorted(texts))
    pos = [_cos(vecs[h], vecs[kw]) for h, kw in pos_pairs if h in vecs and kw in vecs]
    neg = [_cos(vecs[h], vecs[kw]) for h, kw in neg_pairs if h in vecs and kw in vecs]
    return {"gate": "relevance_floor", "config_key": "brief_relevance_floor (pipeline-api)",
            "current": getattr(settings, "brief_relevance_floor", 0.55),
            "positives(kept)": _summary(pos), "negatives(discarded)": _summary(neg),
            **_best_floor(pos, neg)}


def calibrate_restatement_ceiling(briefs, embed) -> dict:
    keep_pairs, drop_pairs, texts = [], [], set()
    for p in briefs:
        title = (p.get("title") or "").strip()
        if not title:
            continue
        texts.add(title)
        for h in _headings(p):
            keep_pairs.append((h, title)); texts.add(h)
        for h in _discarded(p, {"region_restates_title", "above_restatement_ceiling",
                                "h3_above_parent_restatement_ceiling"}):
            drop_pairs.append((h, title)); texts.add(h)
    vecs = embed(sorted(texts))
    keep = [_cos(vecs[h], vecs[t]) for h, t in keep_pairs if h in vecs and t in vecs]
    drop = [_cos(vecs[h], vecs[t]) for h, t in drop_pairs if h in vecs and t in vecs]
    return {"gate": "restatement_ceiling", "config_key": "brief_restatement_ceiling (pipeline-api)",
            "current": getattr(settings, "brief_restatement_ceiling", 0.78),
            "kept(below)": _summary(keep), "dropped(restatements)": _summary(drop),
            **_best_ceiling(keep, drop)}


def calibrate_silo_dedup(embed) -> dict:
    rows = (get_supabase().table("silo_candidates")
            .select("client_id, suggested_keyword").execute().data or [])
    by_client: dict[str, list[str]] = {}
    for r in rows:
        kw = (r.get("suggested_keyword") or "").strip()
        if kw:
            by_client.setdefault(r["client_id"], []).append(kw)
    texts = sorted({k for ks in by_client.values() for k in ks})
    vecs = embed(texts)
    cross = []  # different silos, same client -> should NOT merge (be below threshold)
    for ks in by_client.values():
        for i in range(len(ks)):
            for j in range(i + 1, len(ks)):
                if ks[i] in vecs and ks[j] in vecs:
                    cross.append(_cos(vecs[ks[i]], vecs[ks[j]]))
    # Set the dedup floor safely ABOVE the cross-silo distribution so distinct
    # silos don't merge; P99 + a small margin.
    rec = round(min(0.97, _pct(cross, 99) + 0.02), 3) if cross else None
    return {"gate": "silo_dedup", "config_key": "silo_dedup_cosine_threshold",
            "current": getattr(settings, "silo_dedup_cosine_threshold", 0.85),
            "cross_silo_negatives": _summary(cross),
            "recommended": rec,
            "policy": "P99 of cross-silo (different-silo) cosines + 0.02 margin — keep distinct silos apart",
            "note": "positives (true duplicate keywords that merged) are not persisted separately; "
                    "validate the recommended floor by shadow-deduping a few briefs."}


GATES = {
    "relevance_floor": lambda b, e: calibrate_relevance_floor(b, e),
    "restatement_ceiling": lambda b, e: calibrate_restatement_ceiling(b, e),
    "silo_dedup": lambda b, e: calibrate_silo_dedup(e),
}


def main() -> int:
    ap = argparse.ArgumentParser(description="Recommend Gemini cosine thresholds.")
    ap.add_argument("--gate", choices=list(GATES), help="one gate (default: all)")
    ap.add_argument("--model", default=settings.silo_embedding_model)
    ap.add_argument("--dim", type=int, default=settings.silo_embedding_dimensions)
    ap.add_argument("--limit-briefs", type=int, default=0, help="cap briefs sampled (0=all)")
    ap.add_argument("--json", help="also write the full report to this path")
    args = ap.parse_args()

    if not settings.gemini_api_key:
        print("GEMINI_API_KEY not configured — aborting.", file=sys.stderr)
        return 2
    embed = _make_embedder(args.model, args.dim, settings.gemini_api_key)
    print(f"# Calibrating against model={args.model} dim={args.dim}\n")

    gates = [args.gate] if args.gate else list(GATES)
    briefs: list[dict] = []
    if any(g != "silo_dedup" for g in gates):
        briefs = _load_briefs(args.limit_briefs)
        print(f"# Loaded {len(briefs)} briefs\n")
    report = []
    for g in gates:
        res = GATES[g](briefs, embed)
        report.append(res)
        print(f"## {res['gate']}  ({res['config_key']})")
        for k, v in res.items():
            if k in ("gate", "config_key"):
                continue
            print(f"    {k}: {v}")
        cur = res.get("current"); rec = res.get("recommended")
        if cur is not None and rec is not None:
            print(f"    >>> RECOMMENDED: {res['config_key']} {cur} -> {rec}\n")
        else:
            print()

    if args.json:
        with open(args.json, "w") as f:
            json.dump(report, f, indent=2)
        print(f"# wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
