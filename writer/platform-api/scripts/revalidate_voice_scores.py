"""Re-score the voice-scored pages through the production nlp path and compare
against the stored baseline — the validation gate for a voice-rubric change.

Why this exists
---------------
The brand-voice judge was hardened to stop scoring off-brand pages in the
low-80s (PR that touched ``nlp-api/main.py::_VOICE_SCORE_PROMPT_SUFFIX`` and
``pipeline-api/.../voice_review.py::_SCORE_SYSTEM``). The rubric lives in a
prompt, so the only honest way to know it worked is to re-score real pages on
the deployed service and watch the distribution move. Voice scores are stored
on the page rows, so the *baseline* costs nothing to read; only the re-score
spends (one SERP + one scoring LLM call per page, the exact production cost of
clicking "Score" in the UI).

What it does
------------
For every page carrying a voice score (``local_seo_pages`` + ``ecommerce_pages``,
``voice_score IS NOT NULL``):

  1. captures the stored baseline (headline score + per-dimension scores) in
     memory FIRST, so the before/after survives even a ``--write`` run;
  2. re-scores it through the same service function the UI calls
     (``score_page`` → resolves the client's voice card + SERP → nlp), reading
     ``voice_compliance.score`` off the response;
  3. prints a per-page before→after table, a per-dimension before/after mean,
     and the headline distribution (min/avg/median/max, count<80, count>=90)
     for both eras.

It is READ-ONLY w.r.t. the baseline by default: like clicking "Score" in the UI
it DOES insert one score-history row (``local_seo_page_scores`` /
``ecommerce_page_scores``, best-effort), but it never touches the page's
``voice_score`` / ``voice_violations`` baseline, so the comparison stays intact.
Pass ``--write`` to persist the new scorecard onto the page rows once you trust
it (the in-memory before/after is still printed first).

Two caveats to read the output with:

  * Re-score uses the client's CURRENT voice card. If a client edited their
    brand guide since a page was first scored, that page's before/after mixes
    the guide change with the rubric change — so this is a clean rubric
    comparison only for pages whose guide is unchanged (all the recently-scored
    ones). It is NOT a way to re-score old pages against their original guide.
  * A local page whose stored ``location`` is empty or no longer resolves
    against the client's country list makes ``score_page`` raise
    ``location_not_recognized`` (there is no ``location_code`` on the page row
    to bypass resolution). Such pages surface as ``ERROR`` rows and drop out of
    the comparison — watch the error count, they are excluded, not scored 0.

Where to run it
---------------
nlp-api is private (Railway internal network), so this must run where PLATFORM's
env + private networking are available — a Railway shell on the PLATFORM
service, or any host with the platform-api env. It cannot run from the sandbox.

    # Railway shell on PLATFORM:
    python scripts/revalidate_voice_scores.py                 # compare only
    python scripts/revalidate_voice_scores.py --limit 2       # smoke test first
    python scripts/revalidate_voice_scores.py --csv /tmp/voice.csv
    python scripts/revalidate_voice_scores.py --write         # persist new scores

Exit code 0 on completion (even if some pages error — they're reported); 1 only
on a bootstrap failure (no pages, import/env problem).
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import statistics
import sys
from pathlib import Path
from typing import Any, Optional

# Allow ``from services import …`` when run as ``python scripts/…``.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.supabase_client import get_supabase  # noqa: E402
from services import ecommerce_service, local_seo_service  # noqa: E402

# The eight scorecard dimensions, in the order the rubric defines them.
DIMENSIONS = [
    "tone", "writing_style", "person", "vocabulary",
    "audience_fit", "pain_points", "cta_fit", "distinctiveness",
]


def _dim_scores(voice_violations: Optional[dict]) -> dict[str, Optional[float]]:
    """Per-dimension scores from a stored/returned scorecard.

    Mirrors ``voice_card._dimension_score``: a dimension the judge marked
    ``applicable: false`` contributes None, not its placeholder score. Those
    dimensions are renormalized out of the headline score, so counting a
    placeholder 0 in a per-dimension mean would understate that dimension for
    every guide that happens to be silent on it. ``bool`` is excluded too — a
    JSON ``true``/``false`` in the score slot is malformed, not a 0/1."""
    dims = (voice_violations or {}).get("dimensions") or {}
    out: dict[str, Optional[float]] = {}
    for key in DIMENSIONS:
        entry = dims.get(key)
        if not isinstance(entry, dict) or entry.get("applicable") is False:
            out[key] = None
            continue
        score = entry.get("score")
        out[key] = (
            float(score)
            if isinstance(score, (int, float)) and not isinstance(score, bool)
            else None
        )
    return out


def _fetch_pages() -> list[dict]:
    """Every voice-scored page from both tables, newest first, with baseline."""
    sb = get_supabase()
    rows: list[dict] = []

    local = (
        sb.table("local_seo_pages")
        .select("id, client_id, keyword, location, content_html, voice_score, "
                "voice_violations, deleted_at, created_at")
        .not_.is_("voice_score", "null")
        .order("created_at", desc=True)
        .execute()
    )
    for r in local.data or []:
        rows.append({**r, "kind": "local_seo"})

    ecom = (
        sb.table("ecommerce_pages")
        .select("id, client_id, keyword, page_type, content_html, voice_score, "
                "voice_violations, deleted_at, created_at")
        .not_.is_("voice_score", "null")
        .order("created_at", desc=True)
        .execute()
    )
    for r in ecom.data or []:
        rows.append({**r, "kind": "ecommerce"})

    return rows


async def _rescore(page: dict) -> dict:
    """Re-score one page via the production path. Returns the nlp scorecard, or
    ``{"error": …}`` — one bad page never aborts the run."""
    try:
        if page["kind"] == "local_seo":
            result = await local_seo_service.score_page(
                client_id=page["client_id"],
                keyword=page["keyword"],
                location=page.get("location") or "",
                location_code=None,
                page_url=None,
                page_content=page.get("content_html"),
                serp_analysis=None,
            )
        else:
            result = await ecommerce_service.score_page(
                client_id=page["client_id"],
                keyword=page["keyword"],
                page_type=page.get("page_type") or "product",
                page_url=None,
                page_content=page.get("content_html"),
                serp_analysis=None,
            )
        return result.get("voice_compliance") or {"error": "no_voice_compliance_in_response"}
    except Exception as exc:  # noqa: BLE001 — deliberately catch-all; report + continue
        return {"error": f"{type(exc).__name__}: {exc}"}


def _persist(page: dict, scorecard: dict) -> None:
    """Overwrite the page's stored voice baseline with the new scorecard (--write)."""
    table = "local_seo_pages" if page["kind"] == "local_seo" else "ecommerce_pages"
    get_supabase().table(table).update({
        "voice_score": scorecard.get("score"),
        "voice_violations": scorecard,
    }).eq("id", page["id"]).execute()


def _fmt(x: Optional[float]) -> str:
    return "  —  " if x is None else f"{x:5.1f}"


def _dist(scores: list[float]) -> str:
    if not scores:
        return "no scores"
    return (
        f"n={len(scores)}  min={min(scores):.1f}  avg={statistics.mean(scores):.1f}  "
        f"median={statistics.median(scores):.1f}  max={max(scores):.1f}  "
        f"<80={sum(1 for s in scores if s < 80)}  >=90={sum(1 for s in scores if s >= 90)}"
    )


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0,
                        help="Re-score at most N pages (smoke test). 0 = all.")
    parser.add_argument("--concurrency", type=int, default=2,
                        help="Pages scored in parallel (nlp /score-page is 10/min). "
                             "score_page mixes sync Supabase reads with async SERP/LLM "
                             "calls, so this overlaps the slow network waits, not the "
                             "blocking DB reads — raising it past ~3 buys little.")
    parser.add_argument("--write", action="store_true",
                        help="Persist the new scorecard onto the page rows "
                             "(overwrites the stored baseline).")
    parser.add_argument("--csv", type=str, default="",
                        help="Also write per-page results to this CSV path.")
    args = parser.parse_args()

    pages = _fetch_pages()
    if not pages:
        print("No voice-scored pages found — nothing to validate.", file=sys.stderr)
        return 1
    if args.limit:
        pages = pages[: args.limit]

    print(f"Re-scoring {len(pages)} page(s) "
          f"(concurrency={args.concurrency}, write={args.write})…\n")

    sem = asyncio.Semaphore(max(1, args.concurrency))

    async def _one(page: dict) -> dict:
        async with sem:
            baseline_score = page.get("voice_score")
            baseline_score = float(baseline_score) if baseline_score is not None else None
            baseline_dims = _dim_scores(page.get("voice_violations"))
            scorecard = await _rescore(page)
            new_score = scorecard.get("score") if isinstance(scorecard, dict) else None
            new_score = float(new_score) if isinstance(new_score, (int, float)) else None
            if args.write and new_score is not None and "error" not in scorecard:
                _persist(page, scorecard)
            return {
                "page": page,
                "baseline_score": baseline_score,
                "baseline_dims": baseline_dims,
                "new_score": new_score,
                "new_dims": _dim_scores(scorecard) if isinstance(scorecard, dict) else {},
                "analysis": scorecard.get("analysis") if isinstance(scorecard, dict) else None,
                "error": scorecard.get("error") if isinstance(scorecard, dict) else None,
            }

    results = await asyncio.gather(*[_one(p) for p in pages])

    # ── Per-page table ─────────────────────────────────────────────────────
    print(f"{'kind':10} {'keyword':32} {'base':>6} {'new':>6} {'Δ':>7}  {'band / note'}")
    print("-" * 92)
    for res in results:
        p = res["page"]
        base, new = res["baseline_score"], res["new_score"]
        delta = f"{new - base:+.1f}" if base is not None and new is not None else "   —"
        if res["error"]:
            note = f"ERROR {res['error'][:40]}"
        elif res["analysis"] and res["analysis"] != "full":
            note = f"analysis={res['analysis']}"
        else:
            note = ""
        kw = (p.get("keyword") or "")[:32]
        deleted = " (deleted)" if p.get("deleted_at") else ""
        print(f"{p['kind']:10} {kw:32} {_fmt(base)} {_fmt(new)} {delta:>7}  {note}{deleted}")

    # ── Headline distribution before/after ─────────────────────────────────
    base_scores = [r["baseline_score"] for r in results if r["baseline_score"] is not None]
    new_scores = [r["new_score"] for r in results if r["new_score"] is not None]
    moved = [(r["new_score"] - r["baseline_score"])
             for r in results
             if r["baseline_score"] is not None and r["new_score"] is not None]
    print("\n── Headline distribution ──")
    print(f"  BEFORE : {_dist(base_scores)}")
    print(f"  AFTER  : {_dist(new_scores)}")
    if moved:
        print(f"  Δ      : mean {statistics.mean(moved):+.1f}  "
              f"down={sum(1 for d in moved if d < 0)}  up={sum(1 for d in moved if d > 0)}  "
              f"unchanged={sum(1 for d in moved if d == 0)}")

    # ── Per-dimension mean before/after ────────────────────────────────────
    print("\n── Per-dimension mean (before → after) ──")
    for key in DIMENSIONS:
        b = [r["baseline_dims"].get(key) for r in results if r["baseline_dims"].get(key) is not None]
        a = [r["new_dims"].get(key) for r in results if r["new_dims"].get(key) is not None]
        b_mean = f"{statistics.mean(b):5.1f}" if b else "  —  "
        a_mean = f"{statistics.mean(a):5.1f}" if a else "  —  "
        arrow = ""
        if b and a:
            arrow = f"  ({statistics.mean(a) - statistics.mean(b):+.1f})"
        print(f"  {key:16} {b_mean} → {a_mean}{arrow}")

    errors = [r for r in results if r["error"]]
    if errors:
        loc_errors = [r for r in errors if "location_not_recognized" in (r["error"] or "")]
        print(f"\n{len(errors)} page(s) errored and are EXCLUDED from the "
              f"distributions above (not scored 0).")
        if loc_errors:
            print(f"  {len(loc_errors)} were location-resolution failures "
                  f"(empty/unrecognized stored location) — see caveat below.")

    print("\nCaveat: re-scores use each client's CURRENT voice card, so a "
          "before/after is a clean rubric comparison only where the guide is "
          "unchanged since the page was first scored.")

    if args.csv:
        with open(args.csv, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["kind", "page_id", "client_id", "keyword",
                        "baseline_score", "new_score", "delta", "analysis", "error"])
            for r in results:
                p = r["page"]
                base, new = r["baseline_score"], r["new_score"]
                delta = (new - base) if base is not None and new is not None else ""
                w.writerow([p["kind"], p["id"], p["client_id"], p.get("keyword"),
                            base, new, delta, r["analysis"], r["error"]])
        print(f"\nWrote {args.csv}")

    if args.write:
        print("\n--write was set: page baselines were overwritten with the new scores.")
    else:
        print("\nRead-only run: stored baselines untouched. Re-run with --write to persist.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
