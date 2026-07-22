"""Content illustration — hero + inline body visuals for a finished run.

Runs as the `illustrate_run` async job after a run completes (per-client toggle),
rewriting nothing: it produces an additive `runs.illustrations` layer that the
publish render path interleaves into the article by section anchor, plus a hero
that populates `runs.featured_image_url` (so every destination — GitHub, Docs,
WordPress — gets the hero).

Visual budget (owner spec):
  - hero: always 1 (AI illustration from the title + intro);
  - body: 1 per full 1,000 words, hard-capped at 2, floored at 1 for any article
    with real body sections;
  - total therefore <= 3.

Each body slot is a **chart** when its section carries a chartable set of cited
figures (>=2 related numbers that appear verbatim in the section — integrity is
re-checked so the chart can never show an invented value), else an **AI
illustration** (two-stage: a cheap model art-directs a brand-consistent prompt,
then gpt-image-1 renders it). Charts are deterministic inline SVG (no hosting);
images upload to the public `wordpress_images` bucket as absolute URLs.

Best-effort throughout: any per-visual failure is skipped, never fatal; the job
records what it produced. The pure helpers (planning, integrity, SVG, interleave)
are unit-tested; everything that calls OpenAI/Supabase is impure and mocked.
"""
from __future__ import annotations

import base64
import json
import logging
import re
from html import escape

from config import settings

logger = logging.getLogger(__name__)

# Sections that are structural, not prose — never get a visual anchored after
# them, and don't count toward the chartable/illustratable body.
_SKIP_HEADING_RE = re.compile(
    r"^\s*(key\s+takeaways|takeaways|sources?\s+cited|references?|faq|frequently\s+asked|"
    r"conclusion|in\s+conclusion|summary|call\s+to\s+action)\b",
    re.IGNORECASE,
)
_SKIP_TYPES = {"sources-cited-header", "sources-cited-body", "cta", "key-takeaways"}

# Numbers, percentages, currency — matches the research module's integrity regex
# so a chart value must appear verbatim in the section text.
_NUMERIC_TOKEN_RE = re.compile(r"\$?\d[\d,]*\.?\d*%?")
_TAG_RE = re.compile(r"<[^>]+>")
_MIN_SECTION_WORDS = 40  # a real body section, not a one-line transition


# ── pure: text + planning ────────────────────────────────────────────────────
def strip_html(html: str) -> str:
    """Plain text from an HTML fragment (tags removed, whitespace collapsed)."""
    text = _TAG_RE.sub(" ", html or "")
    text = (
        text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        .replace("&#39;", "'").replace("&quot;", '"').replace("&nbsp;", " ")
    )
    return re.sub(r"\s+", " ", text).strip()


def section_text(section: dict) -> str:
    """A section's heading + body as plain text."""
    heading = (section.get("heading") or "").strip()
    body = strip_html(section.get("body") or "")
    if heading and body:
        return f"{heading}. {body}"
    return heading or body


def count_words(sections: list[dict]) -> int:
    """Total prose word count across the article's section bodies + headings."""
    words = 0
    for s in sections:
        if isinstance(s, dict):
            words += len(section_text(s).split())
    return words


def is_eligible_body_section(section: dict) -> bool:
    """A section a body visual may be anchored after: has a heading, has enough
    real prose, and isn't a structural block (takeaways/CTA/sources/FAQ/etc.)."""
    if not isinstance(section, dict):
        return False
    if section.get("type") in _SKIP_TYPES:
        return False
    heading = (section.get("heading") or "").strip()
    if not heading or _SKIP_HEADING_RE.match(heading):
        return False
    return len(strip_html(section.get("body") or "").split()) >= _MIN_SECTION_WORDS


def plan_body_count(word_count: int, eligible_count: int, floor_one_body: bool = True) -> int:
    """Body-visual count: 1 per full 1,000 words, capped at 2, floored at 1 for
    any article that has an eligible body section (so short posts still break up).
    Zero when there are no eligible sections."""
    if eligible_count <= 0:
        return 0
    n = word_count // 1000
    if floor_one_body:
        n = max(1, n)
    return max(0, min(2, min(n, eligible_count)))


def select_body_anchors(eligible: list[dict], n: int) -> list[int]:
    """Pick `n` section `order`s to anchor body visuals after, spread evenly
    across the eligible sections (so two visuals don't clump). Returns the chosen
    orders in document order."""
    if n <= 0 or not eligible:
        return []
    ordered = sorted(eligible, key=lambda s: s.get("order", 0))
    m = len(ordered)
    if n >= m:
        return [s.get("order", 0) for s in ordered]
    # Even spread: for n picks over m slots, take positions at the centres of n
    # equal buckets (skews slightly later, which reads well after intro prose).
    picks = [ordered[int((i + 1) * m / (n + 1))] for i in range(n)]
    seen: set[int] = set()
    out: list[int] = []
    for s in picks:
        o = s.get("order", 0)
        if o not in seen:
            seen.add(o)
            out.append(o)
    # Backfill if rounding collided.
    for s in ordered:
        if len(out) >= n:
            break
        o = s.get("order", 0)
        if o not in seen:
            seen.add(o)
            out.append(o)
    return sorted(out)


# ── pure: chart integrity + SVG ──────────────────────────────────────────────
def _numeric_tokens(text: str) -> list[str]:
    return [t.replace(",", "") for t in _NUMERIC_TOKEN_RE.findall(text or "")]


def verify_series_integrity(series: list[dict], source_text: str) -> bool:
    """Every series value must appear verbatim (as a numeric token) in the source
    section text — the same integrity bar the research module enforces on claims.
    Rejects an invented or rounded value. Requires >=2 usable points."""
    source_tokens = set(_numeric_tokens(source_text))
    if not source_tokens:
        return False
    ok = 0
    for point in series:
        if not isinstance(point, dict):
            return False
        raw = point.get("value")
        if raw is None:
            return False
        # Normalise the model's value to the token forms that could appear in
        # prose: "45", "45.0" -> "45"; keep a percent variant too.
        try:
            num = float(str(raw).replace(",", "").rstrip("%"))
        except (TypeError, ValueError):
            return False
        cands = {str(raw).replace(",", "").strip()}
        if num.is_integer():
            cands.add(str(int(num)))
        else:
            cands.add(("%f" % num).rstrip("0").rstrip("."))
        cands |= {f"{c}%" for c in list(cands)}
        if cands & source_tokens:
            ok += 1
        else:
            return False  # a value we can't ground — reject the whole chart
    return ok >= 2


def _svg_num(x: float) -> str:
    return ("%.2f" % x).rstrip("0").rstrip(".")


def render_bar_chart_svg(
    title: str, series: list[dict], unit: str = "", *,
    color: str = "#9554ff", axis: str = "#8c8ea3", text: str = "#070523",
    width: int = 640,
) -> str:
    """A dependency-free horizontal bar chart as inline SVG (bfe palette by
    default). `series` is [{label, value}]; values are shown as given (already
    integrity-checked upstream). Scales to the max value; labels left, bars
    centre, values right."""
    pts = [
        {"label": str(p.get("label", "")).strip(), "value": float(str(p.get("value")).replace(",", "").rstrip("%"))}
        for p in series
        if isinstance(p, dict) and p.get("value") is not None
    ]
    if not pts:
        return ""
    row_h, gap, pad_top, pad_bottom = 34, 10, 44, 16
    label_w, value_w = 200, 70
    bar_x = label_w + 12
    bar_max = width - bar_x - value_w - 12
    peak = max((p["value"] for p in pts), default=0) or 1.0
    height = pad_top + pad_bottom + len(pts) * row_h + (len(pts) - 1) * gap
    parts = [
        f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" '
        f'xmlns="http://www.w3.org/2000/svg" style="max-width:{width}px;font-family:system-ui,sans-serif">',
        f'<title>{escape(title)}</title>',
        f'<text x="0" y="24" font-size="17" font-weight="700" fill="{text}">{escape(title)}</text>',
    ]
    for i, p in enumerate(pts):
        y = pad_top + i * (row_h + gap)
        bar_w = max(2.0, (p["value"] / peak) * bar_max)
        val_label = _svg_num(p["value"]) + (unit if unit and not unit.isspace() else "")
        parts.append(
            f'<text x="{label_w}" y="{y + row_h * 0.66:.0f}" font-size="13" text-anchor="end" '
            f'fill="{text}">{escape(p["label"][:40])}</text>'
        )
        parts.append(
            f'<rect x="{bar_x}" y="{y + 6}" width="{_svg_num(bar_w)}" height="{row_h - 12}" '
            f'rx="4" fill="{color}"/>'
        )
        parts.append(
            f'<text x="{_svg_num(bar_x + bar_w + 8)}" y="{y + row_h * 0.66:.0f}" font-size="13" '
            f'font-weight="600" fill="{axis}">{escape(val_label)}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


# ── pure: figure HTML + interleave ───────────────────────────────────────────
def figure_html_image(url: str, alt: str, caption: str = "") -> str:
    cap = f'<figcaption>{escape(caption)}</figcaption>' if caption else ""
    return (
        f'<figure class="post-figure"><img src="{escape(url, quote=True)}" '
        f'alt="{escape(alt, quote=True)}" loading="lazy" />{cap}</figure>'
    )


def figure_html_chart(svg: str, caption: str = "") -> str:
    cap = f'<figcaption>{escape(caption)}</figcaption>' if caption else ""
    return f'<figure class="post-figure post-chart">{svg}{cap}</figure>'


def _figure_html(item: dict) -> str:
    if item.get("kind") == "chart" and item.get("svg"):
        return figure_html_chart(item["svg"], item.get("caption", ""))
    if item.get("url"):
        return figure_html_image(item["url"], item.get("alt", ""), item.get("caption", ""))
    return ""


def interleave_figures(sections: list[dict], illustrations: dict | None) -> list[dict]:
    """Return the article sections with figure pseudo-sections inserted after each
    body item's anchor order. A figure section carries `{type:'figure', html:...}`
    which every render path emits as raw HTML. Hero is NOT interleaved (it rides
    featured_image_url). Input order is preserved."""
    if not isinstance(illustrations, dict):
        return sections
    items = illustrations.get("items") or []
    by_anchor: dict[int, list[str]] = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        html = _figure_html(it)
        if html:
            by_anchor.setdefault(int(it.get("anchor_order", 0)), []).append(html)
    if not by_anchor:
        return sections
    out: list[dict] = []
    for s in sorted((x for x in sections if isinstance(x, dict)), key=lambda x: x.get("order", 0)):
        out.append(s)
        for html in by_anchor.get(int(s.get("order", 0)), []):
            out.append({"type": "figure", "order": s.get("order", 0), "heading": None, "body": None, "html": html})
    return out


# ── impure: OpenAI briefs + image gen ────────────────────────────────────────
def _openai_client():
    import openai  # lazy (keeps the sandbox importable without the dep)

    return openai.AsyncOpenAI(api_key=settings.openai_api_key)


_BRIEF_SYSTEM = (
    "You are an art director for a marketing blog. Given one article section, write a concise "
    "prompt for an editorial ILLUSTRATION that sits beside it, plus SEO alt text describing what "
    "the image shows. Rules: no text/words/letters/numbers/charts/graphs/logos in the image; "
    "depict a scene or concept, never data; keep it brand-safe and literal to the section. "
    'Respond ONLY as JSON: {"image_prompt": "...", "alt_text": "..."}.'
)
_CHART_SYSTEM = (
    "You extract a chartable data series from ONE article section, ONLY when the section states a "
    "set of at least two RELATED, comparable figures (e.g. percentages of a whole, values across "
    "named categories, before/after). Use the section's EXACT numbers — never invent, round, or "
    "infer. If there is no genuinely comparable set, return chartable=false. "
    'Respond ONLY as JSON: {"chartable": bool, "title": "short chart title", "unit": "%|$|"" , '
    '"caption": "one line naming the source", "series": [{"label": "...", "value": number}]}.'
)


def _brand_style_suffix(client: dict) -> str:
    """A fixed style suffix appended to every image prompt so a post's images read
    as a set. Uses the client's brand voice tone if present, else a clean default."""
    base = "flat editorial vector illustration, soft purple and lavender palette, clean, modern, no text"
    voice = client.get("brand_voice")
    tone = ""
    if isinstance(voice, dict):
        t = voice.get("tone") or voice.get("summary")
        if isinstance(t, str) and t.strip():
            tone = f", {t.strip()[:80]}"
    return base + tone


async def _image_brief(text: str, client: dict, *, hero: bool = False) -> dict | None:
    """Two-stage step one: art-direct a brand-consistent prompt + alt text."""
    try:
        oc = _openai_client()
        prompt = ("This is the article's opening. " if hero else "") + f"Section:\n{text[:2000]}"
        resp = await oc.chat.completions.create(
            model=settings.illustration_brief_model,
            messages=[{"role": "system", "content": _BRIEF_SYSTEM}, {"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_tokens=300,
        )
        data = json.loads(resp.choices[0].message.content or "{}")
        p, alt = (data.get("image_prompt") or "").strip(), (data.get("alt_text") or "").strip()
        if not p:
            return None
        return {"prompt": f"{p}. {_brand_style_suffix(client)}", "alt": alt or p[:120]}
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.warning("illustration.brief_failed", extra={"error": str(exc)})
        return None


async def _chart_series(text: str) -> dict | None:
    """Two-stage step one for charts: extract a comparable series, then enforce
    numeric integrity against the section. Returns {title,unit,caption,series}
    or None."""
    try:
        oc = _openai_client()
        resp = await oc.chat.completions.create(
            model=settings.illustration_brief_model,
            messages=[{"role": "system", "content": _CHART_SYSTEM}, {"role": "user", "content": text[:2500]}],
            response_format={"type": "json_object"},
            max_tokens=400,
        )
        data = json.loads(resp.choices[0].message.content or "{}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("illustration.chart_extract_failed", extra={"error": str(exc)})
        return None
    if not data.get("chartable"):
        return None
    series = [p for p in (data.get("series") or []) if isinstance(p, dict)]
    if len(series) < 2 or not verify_series_integrity(series, text):
        return None
    return {
        "title": (data.get("title") or "").strip()[:80] or "By the numbers",
        "unit": (data.get("unit") or "").strip(),
        "caption": (data.get("caption") or "").strip()[:160],
        "series": series[:8],
    }


async def _generate_image(prompt: str) -> bytes | None:
    try:
        oc = _openai_client()
        resp = await oc.images.generate(
            model=settings.illustration_image_model,
            prompt=prompt[:4000],
            size=settings.illustration_image_size,
            n=1,
        )
        b64 = resp.data[0].b64_json
        return base64.b64decode(b64) if b64 else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("illustration.image_gen_failed", extra={"error": str(exc)})
        return None


_IMAGE_BUCKET = "wordpress_images"


def _upload_image(supabase, run_id: str, idx: str, png: bytes) -> str | None:
    path = f"illustrations/{run_id}/{idx}.png"
    try:
        supabase.storage.from_(_IMAGE_BUCKET).upload(
            path, png, {"content-type": "image/png", "upsert": "true"}
        )
        res = supabase.storage.from_(_IMAGE_BUCKET).get_public_url(path)
        if isinstance(res, str):
            return res
        if isinstance(res, dict):
            return res.get("publicURL") or res.get("publicUrl")
    except Exception as exc:  # noqa: BLE001
        logger.warning("illustration.upload_failed", extra={"path": path, "error": str(exc)})
    return None


# ── impure: orchestration + job ──────────────────────────────────────────────
def _load_article(supabase, run_id: str) -> list[dict]:
    rows = (
        supabase.table("module_outputs")
        .select("output_payload")
        .eq("run_id", run_id).eq("module", "sources_cited").eq("status", "complete")
        .execute()
    ).data or []
    if not rows:
        return []
    article = ((rows[0].get("output_payload") or {}).get("enriched_article") or {}).get("article") or []
    return [s for s in article if isinstance(s, dict)]


async def generate_run_illustrations(run_id: str) -> dict:
    """Plan + generate a run's hero and inline body visuals. Writes
    runs.illustrations (+ featured_image_url for the hero). Returns the record."""
    from db.supabase_client import get_supabase

    supabase = get_supabase()
    run = (
        supabase.table("runs").select("id, client_id, keyword, featured_image_url")
        .eq("id", run_id).single().execute()
    ).data
    if not run:
        raise ValueError("run_not_found")
    client = (
        supabase.table("clients").select("name, brand_voice").eq("id", run["client_id"]).single().execute()
    ).data or {}

    sections = _load_article(supabase, run_id)
    word_count = count_words(sections)
    eligible = [s for s in sections if is_eligible_body_section(s)]
    body_n = plan_body_count(word_count, len(eligible))
    anchors = select_body_anchors(eligible, body_n)
    by_order = {s.get("order"): s for s in eligible}

    record: dict = {"status": "complete", "word_count": word_count, "items": [], "notes": []}

    # Body slots: chart if the section has chartable cited data, else illustration.
    for i, anchor in enumerate(anchors):
        sec = by_order.get(anchor)
        if not sec:
            continue
        text = section_text(sec)
        chart = await _chart_series(text)
        if chart:
            svg = render_bar_chart_svg(chart["title"], chart["series"], chart["unit"])
            if svg:
                record["items"].append({
                    "anchor_order": anchor, "kind": "chart", "svg": svg,
                    "caption": chart["caption"], "alt": chart["title"],
                })
                continue
        brief = await _image_brief(text, client)
        if not brief:
            record["notes"].append(f"section {anchor}: no brief")
            continue
        png = await _generate_image(brief["prompt"])
        if not png:
            record["notes"].append(f"section {anchor}: image gen failed")
            continue
        url = _upload_image(supabase, run_id, f"body-{i}", png)
        if not url:
            record["notes"].append(f"section {anchor}: upload failed")
            continue
        record["items"].append({"anchor_order": anchor, "kind": "image", "url": url, "alt": brief["alt"], "caption": ""})

    # Hero: always an illustration from the title + intro (first eligible section
    # or the lead prose). Only set if the run has no hero yet.
    hero_url = None
    if not run.get("featured_image_url"):
        intro = section_text(sections[0]) if sections else ""
        hero_text = f"{run.get('keyword', '')}. {intro}".strip(". ")
        brief = await _image_brief(hero_text, client, hero=True)
        if brief:
            png = await _generate_image(brief["prompt"])
            if png:
                hero_url = _upload_image(supabase, run_id, "hero", png)
                if hero_url:
                    record["hero"] = {"url": hero_url, "alt": brief["alt"]}

    update: dict = {"illustrations": record}
    if hero_url:
        update["featured_image_url"] = hero_url
    supabase.table("runs").update(update).eq("id", run_id).execute()
    logger.info(
        "illustration.generated",
        extra={"run_id": run_id, "body": len(record["items"]), "hero": bool(hero_url), "words": word_count},
    )
    return record


async def run_illustrate_job(job: dict) -> None:
    payload = job.get("payload") or {}
    run_id = payload.get("run_id") or job.get("entity_id")
    if not run_id:
        raise ValueError("illustrate_run: missing run_id")
    await generate_run_illustrations(str(run_id))


def enqueue_illustrate_run(run_id: str, *, force: bool = False) -> bool:
    """Queue an illustrate_run job for a completed run. When not forced (the
    auto path), gates on the global flag AND the client's illustrate_content
    toggle. Best-effort — never raises into the caller. Returns True if enqueued."""
    from db.supabase_client import get_supabase

    supabase = get_supabase()
    try:
        if not force:
            if not settings.illustration_enabled:
                return False
            run = (
                supabase.table("runs").select("client_id").eq("id", run_id).single().execute()
            ).data
            if not run:
                return False
            client = (
                supabase.table("clients").select("illustrate_content").eq("id", run["client_id"]).single().execute()
            ).data or {}
            if not client.get("illustrate_content"):
                return False
        supabase.table("async_jobs").insert(
            {"job_type": "illustrate_run", "entity_id": run_id, "payload": {"run_id": run_id}}
        ).execute()
        return True
    except Exception as exc:  # noqa: BLE001 — advisory enqueue
        logger.warning("illustration.enqueue_failed", extra={"run_id": run_id, "error": str(exc)})
        return False
