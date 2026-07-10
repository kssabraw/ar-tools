"""Organic rank tracker — plain-English overview summary.

A deterministic, LLM-free narrative of how a client's organic keyword tracking
is doing across ALL tracked keywords, rendered at the top of the Rankings
"Overview" tab (the geogrid tab has its per-scan Local Rank Analysis narrative;
this is the whole-tracker read for organic). Pure + unit-tested — it reads the
same per-keyword summaries the Overview already computes (rank_status.
compute_keyword_summary), so it never issues a paid call and always renders
instantly. Reusable server-side (the Slack assistant / strategist can cite it).
"""

from __future__ import annotations

from typing import Optional

# Status taxonomy from services.rank_status.compute_status.
_CLIMBING = "climbing"
_DROPPING = "dropping"
_DEINDEX = "deindex_risk"


def _pos(kw: dict) -> Optional[float]:
    """Best current-position estimate: the live rank when present, else the
    30-day GSC average."""
    today = kw.get("today_rank")
    if today is not None:
        return float(today)
    avg30 = kw.get("avg_30")
    return float(avg30) if avg30 is not None else None


def _movement(kw: dict) -> Optional[float]:
    """30-day trend magnitude: positive = improved (recent 7-day average is a
    lower/better position than the 30-day baseline). None when either window is
    empty."""
    a7, a30 = kw.get("avg_7"), kw.get("avg_30")
    if a7 is None or a30 is None:
        return None
    return round(float(a30) - float(a7), 1)


def _fmt_pos(p: Optional[float]) -> str:
    return f"#{round(p)}" if p is not None else "n/a"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def build_rank_summary(
    summaries: list[dict],
    *,
    client_name: Optional[str] = None,
    gsc_connected: bool = False,
    striking_min: int = 4,
    striking_max: int = 20,
    move_threshold: float = 1.0,
) -> dict:
    """Build {headline, narrative, stats, top_gainer, top_decliner} from the
    per-keyword summaries. Pure."""
    total = len(summaries)
    who = f" for {client_name}" if client_name else ""

    if total == 0:
        return {
            "headline": "No keywords tracked yet",
            "narrative": f"No organic keywords are being tracked{who} yet. "
            "Add keywords to start measuring positions, clicks, and trends.",
            "stats": {"keyword_count": 0, "page_one": 0, "striking": 0,
                      "climbing": 0, "dropping": 0, "at_risk": 0,
                      "avg_position": None, "clicks_30d": 0, "impressions_30d": 0},
            "top_gainer": None, "top_decliner": None,
        }

    positions = [p for kw in summaries if (p := _pos(kw)) is not None]
    page_one = sum(1 for p in positions if p <= 10)
    striking = sum(1 for p in positions if striking_min <= p <= striking_max)
    avg_position = round(sum(positions) / len(positions), 1) if positions else None

    climbing = sum(1 for kw in summaries if kw.get("status") == _CLIMBING)
    dropping = sum(1 for kw in summaries if kw.get("status") == _DROPPING)
    at_risk = sum(1 for kw in summaries if kw.get("status") == _DEINDEX)

    clicks_30d = sum(int(kw.get("clicks_30d") or 0) for kw in summaries)
    impressions_30d = sum(int(kw.get("impressions_30d") or 0) for kw in summaries)

    # Named movers by 30-day trend magnitude.
    moved = [(kw, m) for kw in summaries if (m := _movement(kw)) is not None]
    gainers = sorted((x for x in moved if x[1] >= move_threshold), key=lambda x: -x[1])
    decliners = sorted((x for x in moved if x[1] <= -move_threshold), key=lambda x: x[1])
    top_gainer = _mover_obj(gainers[0]) if gainers else None
    top_decliner = _mover_obj(decliners[0]) if decliners else None

    stats = {
        "keyword_count": total, "page_one": page_one, "striking": striking,
        "climbing": climbing, "dropping": dropping, "at_risk": at_risk,
        "avg_position": avg_position, "clicks_30d": clicks_30d,
        "impressions_30d": impressions_30d,
    }

    # ── narrative ──
    sentences: list[str] = []
    if positions:
        lead = f"You're tracking {_plural(total, 'keyword')}{who}, {_plural(page_one, 'on page 1')}"
        if avg_position is not None:
            lead += f", with an average position of {avg_position}"
        sentences.append(lead + ".")
    else:
        sentences.append(
            f"You're tracking {_plural(total, 'keyword')}{who}, all still awaiting their "
            "first ranking data."
        )

    if climbing or dropping:
        trend = f"Over the last 30 days {climbing} climbed and {dropping} slipped"
        bits = []
        if top_gainer:
            bits.append(
                f"the biggest gain was “{top_gainer['keyword']}”, up ~{top_gainer['delta']:g} "
                f"to about {_fmt_pos(top_gainer['position'])}"
            )
        if top_decliner:
            bits.append(
                f"“{top_decliner['keyword']}” fell ~{abs(top_decliner['delta']):g} "
                f"to about {_fmt_pos(top_decliner['position'])}"
            )
        trend += (" — " + ", while ".join(bits)) if bits else ""
        sentences.append(trend + ".")

    if striking:
        sentences.append(
            f"{_plural(striking, 'keyword')} in striking distance (positions "
            f"{striking_min}–{striking_max}) — the quickest wins to push onto page 1."
        )

    if at_risk:
        sentences.append(
            f"{_plural(at_risk, 'keyword')} at deindex risk and need attention."
        )

    if gsc_connected and (clicks_30d or impressions_30d):
        sentences.append(
            f"Search Console recorded {clicks_30d:,} clicks and {impressions_30d:,} "
            "impressions in the last 30 days."
        )

    headline_bits = [_plural(total, "keyword")]
    if positions:
        headline_bits.append(f"{page_one} on page 1")
    if striking:
        headline_bits.append(_plural(striking, "quick win"))
    if at_risk:
        headline_bits.append(f"{at_risk} at risk")

    return {
        "headline": " · ".join(headline_bits),
        "narrative": " ".join(sentences),
        "stats": stats,
        "top_gainer": top_gainer,
        "top_decliner": top_decliner,
    }


def _mover_obj(entry: tuple[dict, float]) -> dict:
    kw, delta = entry
    return {
        "keyword": kw.get("keyword") or "",
        "delta": delta,
        "position": round(kw["avg_7"]) if kw.get("avg_7") is not None else _pos(kw),
    }
