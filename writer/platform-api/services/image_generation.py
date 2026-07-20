"""Blog-post image generation for the GitHub publish path.

Generates a hero image + N body images (illustrations and/or charts) for a
finished blog run with OpenAI `gpt-image-1`, then hands the raw PNG bytes to the
GitHub publish step which commits them into the client's repo alongside the
markdown (one atomic commit) under `public/images/blog/<slug>/`.

Split into a PURE core (word counting, body-image budget, plan parsing, prompt
authoring, repo-path + site-URL building, markdown injection — all unit-tested)
and a thin IMPURE shell (the OpenAI render call, the LLM planning call, the
Supabase preview upload). Best-effort throughout: any failure degrades to fewer
images (or none) — it never blocks a publish.
"""
from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass, field

from config import settings

logger = logging.getLogger(__name__)

# The public content-image bucket (legacy name — it is the suite's general
# content-image store, used by every publish destination, not just WordPress).
_PREVIEW_BUCKET = "wordpress_images"

# gpt-image-1 accepts a fixed set of sizes; anything else 400s. Fall back to a
# square if a misconfigured value slips through.
_VALID_SIZES = {"1024x1024", "1536x1024", "1024x1536", "auto"}


# ── Section model ────────────────────────────────────────────────────────────


@dataclass
class Section:
    """One article section (H2 group) as heading + body markdown."""

    heading: str
    body: str


@dataclass
class ImageSlot:
    """A planned image: what to render and where it lands. `data` (PNG bytes) and
    `preview_url` are filled by the impure render step; the rest is pure."""

    role: str            # 'hero' | 'body'
    kind: str            # 'illustration' | 'chart'
    position: int        # 0 for hero; 1..N for body images (render/file order)
    after_index: int     # body: the section index this image is placed after; hero: -1
    alt: str
    prompt: str
    size: str
    repo_path: str       # committed path in the repo, e.g. public/images/blog/<slug>/hero.png
    site_url: str        # absolute site path the markdown references, e.g. /images/blog/<slug>/hero.png
    data: bytes | None = None
    preview_url: str | None = None
    anchor_heading: str | None = None


# ── Pure: sections + budget ──────────────────────────────────────────────────


def assemble_sections(article: list[dict]) -> list[Section]:
    """Ordered (heading, body) sections from the sources_cited enriched article."""
    if not isinstance(article, list):
        return []
    rows = sorted(
        (s for s in article if isinstance(s, dict)),
        key=lambda s: s.get("order", 0),
    )
    return [Section(heading=(s.get("heading") or "").strip(), body=(s.get("body") or "")) for s in rows]


_WORD_RE = re.compile(r"[A-Za-z0-9']+")


def count_words(sections: list[Section]) -> int:
    """Approximate body word count across all sections (headings + prose)."""
    total = 0
    for s in sections:
        total += len(_WORD_RE.findall(s.heading)) + len(_WORD_RE.findall(s.body))
    return total


def target_body_image_count(
    word_count: int, *, per_1000: float, minimum: int, maximum: int
) -> int:
    """Body-image budget: `per_1000` images per 1000 words, rounded, clamped to
    [minimum, maximum]. A near-empty article yields `minimum`."""
    raw = (max(0, word_count) / 1000.0) * max(0.0, per_1000)
    n = int(raw + 0.5)  # round half up (deterministic; no banker's rounding)
    return max(minimum, min(maximum, n))


# ── Pure: repo paths + site URLs ─────────────────────────────────────────────


def site_url_for_repo_path(repo_path: str) -> str:
    """The absolute site path an Astro/static build serves a committed image at.
    `public/` is served at the site root, so it is stripped; any other base is
    referenced as-is under '/'. Always returns a single leading slash."""
    p = (repo_path or "").lstrip("/")
    if p.startswith("public/"):
        p = p[len("public/"):]
    return "/" + p.lstrip("/")


def image_filename(role: str, position: int, kind: str) -> str:
    """Deterministic file name for an image slot."""
    if role == "hero":
        return "hero.png"
    stem = "chart" if kind == "chart" else "body"
    return f"{stem}-{position}.png"


def build_slot_paths(base: str, slug: str, role: str, position: int, kind: str) -> tuple[str, str]:
    """(repo_path, site_url) for an image slot. `base` is the server default repo
    image path (e.g. public/images/blog); `slug` scopes the post's folder."""
    base_clean = (base or "public/images/blog").strip().strip("/")
    slug_clean = (slug or "post").strip("/") or "post"
    repo_path = f"{base_clean}/{slug_clean}/{image_filename(role, position, kind)}"
    return repo_path, site_url_for_repo_path(repo_path)


# ── Pure: plan parsing ───────────────────────────────────────────────────────

# The forced-tool schema the planner fills. Kept here so the prompt and the parse
# stay in one place.
PLAN_TOOL_NAME = "emit_image_plan"
PLAN_TOOL_DESCRIPTION = (
    "Emit the hero image and the body images for this blog post. The hero is a "
    "single wide editorial image for the top of the post. Each body image is "
    "placed after a specific section and is either an 'illustration' (a "
    "conceptual/editorial picture) or a 'chart' (a data visualization). Choose "
    "'chart' only when the section actually contains numbers/comparisons worth "
    "visualizing, and put the concrete figures/labels into that image's prompt."
)


def plan_input_schema(n_sections: int, n_body: int) -> dict:
    """JSON schema for the planning forced-tool call."""
    return {
        "type": "object",
        "properties": {
            "hero": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Image prompt for the hero."},
                    "alt": {"type": "string", "description": "Concise alt text."},
                },
                "required": ["prompt", "alt"],
            },
            "body": {
                "type": "array",
                "description": f"Exactly {n_body} body images (fewer only if the post is too short).",
                "items": {
                    "type": "object",
                    "properties": {
                        "after_section_index": {
                            "type": "integer",
                            "description": f"0-based section index (0..{max(0, n_sections - 1)}) this image follows.",
                        },
                        "kind": {"type": "string", "enum": ["illustration", "chart"]},
                        "prompt": {"type": "string"},
                        "alt": {"type": "string"},
                    },
                    "required": ["after_section_index", "kind", "prompt", "alt"],
                },
            },
        },
        "required": ["hero", "body"],
    }


def build_plan_system() -> str:
    return (
        "You are an art director for SEO blog posts. You decide the images a post "
        "needs and write concrete, self-contained image-generation prompts. Prompts "
        "must describe exactly what to draw — never reference 'the article' or 'above'. "
        "For a chart, state the chart type, the axis labels, and the actual data values "
        "so the rendered image shows correct numbers. Keep alt text concise and literal."
    )


def build_plan_user(title: str, sections: list[Section], n_body: int) -> str:
    """The planning prompt: the post title + its section outline + how many body
    images to place."""
    lines = [f"POST TITLE: {title or '(untitled)'}", "", "SECTIONS (index — heading — first 400 chars):"]
    for i, s in enumerate(sections):
        body_preview = re.sub(r"\s+", " ", s.body).strip()[:400]
        lines.append(f"[{i}] {s.heading or '(no heading)'} — {body_preview}")
    lines += [
        "",
        f"Produce 1 hero image and exactly {n_body} body image(s). Spread the body "
        "images across different sections (do not stack them). Prefer a chart only "
        "where a section has real quantitative content; otherwise use an illustration.",
    ]
    return "\n".join(lines)


def _clamp_index(idx: object, n_sections: int) -> int:
    try:
        i = int(idx)
    except (TypeError, ValueError):
        return 0
    if n_sections <= 0:
        return 0
    return max(0, min(n_sections - 1, i))


def parse_plan(
    raw: dict,
    *,
    sections: list[Section],
    slug: str,
    n_body: int,
    style_suffix: str,
    hero_size: str,
    body_size: str,
    base_path: str,
) -> list[ImageSlot]:
    """Turn the planner's tool arguments into ordered ImageSlots with resolved
    prompts, sizes, repo paths and site URLs. Defensive: missing/short/oversized
    plans are coerced to a valid set (hero always present; body clamped to
    `n_body` and to valid section indices)."""
    raw = raw if isinstance(raw, dict) else {}
    n_sections = len(sections)
    slots: list[ImageSlot] = []

    # Hero (always exactly one).
    hero = raw.get("hero") if isinstance(raw.get("hero"), dict) else {}
    hero_prompt = (hero.get("prompt") or "").strip() or f"Editorial hero image for a blog post titled '{slug}'."
    repo_path, site_url = build_slot_paths(base_path, slug, "hero", 0, "illustration")
    slots.append(
        ImageSlot(
            role="hero", kind="illustration", position=0, after_index=-1,
            alt=(hero.get("alt") or "").strip() or "Hero image",
            prompt=finalize_prompt(hero_prompt, style_suffix),
            size=_safe_size(hero_size), repo_path=repo_path, site_url=site_url,
        )
    )

    # Body images.
    body = raw.get("body") if isinstance(raw.get("body"), list) else []
    used = 0
    for item in body:
        if used >= n_body:
            break
        if not isinstance(item, dict):
            continue
        prompt = (item.get("prompt") or "").strip()
        if not prompt:
            continue
        kind = "chart" if item.get("kind") == "chart" else "illustration"
        after = _clamp_index(item.get("after_section_index"), n_sections)
        used += 1
        repo_path, site_url = build_slot_paths(base_path, slug, "body", used, kind)
        slots.append(
            ImageSlot(
                role="body", kind=kind, position=used, after_index=after,
                alt=(item.get("alt") or "").strip() or f"{kind.capitalize()} for section {after + 1}",
                prompt=finalize_prompt(prompt, style_suffix if kind == "illustration" else _chart_suffix()),
                size=_safe_size(body_size), repo_path=repo_path, site_url=site_url,
                anchor_heading=sections[after].heading if 0 <= after < n_sections else None,
            )
        )
    return slots


def finalize_prompt(prompt: str, suffix: str) -> str:
    """Append the house-style suffix once (skip if the prompt already ends with it)."""
    prompt = (prompt or "").strip()
    suffix = (suffix or "").strip()
    if not suffix or prompt.endswith(suffix):
        return prompt
    return f"{prompt}\n\n{suffix}"


def _chart_suffix() -> str:
    return (
        "Render as a clean, legible data chart with clearly labeled axes and "
        "accurate values exactly as specified. Minimal, professional styling. "
        "No decorative clutter."
    )


def _safe_size(size: str) -> str:
    return size if size in _VALID_SIZES else "1024x1024"


# ── Pure: markdown assembly with images ──────────────────────────────────────


def render_markdown_with_images(sections: list[Section], body_slots: list[ImageSlot]) -> str:
    """Rebuild the post markdown from sections, injecting each body image's
    `![alt](site_url)` right after the section it anchors to. Slots targeting the
    same section keep their `position` order. The hero is NOT injected here — it
    rides the frontmatter `heroImage`."""
    by_section: dict[int, list[ImageSlot]] = {}
    for slot in body_slots:
        if slot.role != "body":
            continue
        by_section.setdefault(slot.after_index, []).append(slot)
    for lst in by_section.values():
        lst.sort(key=lambda s: s.position)

    parts: list[str] = []
    for i, s in enumerate(sections):
        if s.heading:
            parts.append(f"## {s.heading}\n\n{s.body}".rstrip())
        else:
            parts.append((s.body or "").rstrip())
        for slot in by_section.get(i, []):
            alt = (slot.alt or "").replace("]", "").replace("[", "").strip()
            parts.append(f"![{alt}]({slot.site_url})")
    # Any body slot whose index fell past the section list (shouldn't happen after
    # clamping) is appended at the end so the image is never silently dropped.
    max_idx = len(sections) - 1
    for idx, lst in by_section.items():
        if idx > max_idx:
            for slot in lst:
                alt = (slot.alt or "").strip()
                parts.append(f"![{alt}]({slot.site_url})")
    return "\n\n".join(p for p in parts if p).strip() + "\n"


# ── Impure: OpenAI render + LLM plan + preview upload ─────────────────────────


async def plan_images(title: str, sections: list[Section], n_body: int) -> dict:
    """Ask the planner for the hero + body images. Returns the tool-args dict.
    Raises on total LLM failure (the caller treats it as best-effort)."""
    from services import report_llm

    return await report_llm.run_forced_tool(
        provider="anthropic",
        model=settings.blog_image_plan_model,
        system=build_plan_system(),
        user=build_plan_user(title, sections, n_body),
        tool_name=PLAN_TOOL_NAME,
        tool_description=PLAN_TOOL_DESCRIPTION,
        input_schema=plan_input_schema(len(sections), n_body),
        max_tokens=settings.blog_image_plan_max_tokens,
        log_tag="blog_image_plan",
    )


async def render_image_bytes(prompt: str, size: str) -> bytes:
    """Render one image with gpt-image-1 → raw PNG bytes."""
    import openai

    client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
    resp = await client.images.generate(
        model=settings.blog_image_model,
        prompt=prompt,
        size=_safe_size(size),
        n=1,
    )
    b64 = resp.data[0].b64_json
    if not b64:
        raise RuntimeError("image_generation_empty_response")
    return base64.b64decode(b64)


def upload_preview(data: bytes, repo_path: str) -> str | None:
    """Upload the PNG to the public content bucket for a stable preview/back-compat
    URL (also used as the run's featured_image_url for non-GitHub surfaces).
    Best-effort — returns None on failure."""
    import uuid as _uuid

    from db.supabase_client import get_supabase

    supabase = get_supabase()
    key = f"blog/{_uuid.uuid4().hex}.png"
    try:
        supabase.storage.from_(_PREVIEW_BUCKET).upload(
            key, data, {"content-type": "image/png", "upsert": "true"}
        )
        return supabase.storage.from_(_PREVIEW_BUCKET).get_public_url(key).rstrip("?")
    except Exception as exc:  # noqa: BLE001 — preview is non-fatal
        logger.warning("blog_image.preview_upload_failed", extra={"repo_path": repo_path, "error": str(exc)})
        return None


@dataclass
class GenerationResult:
    """Everything the publish step needs: the slots (with bytes) + the assembled
    markdown that references them."""

    slots: list[ImageSlot] = field(default_factory=list)
    markdown: str = ""

    @property
    def hero(self) -> ImageSlot | None:
        return next((s for s in self.slots if s.role == "hero" and s.data), None)

    @property
    def committable(self) -> list[ImageSlot]:
        return [s for s in self.slots if s.data]


async def generate_blog_images(
    *,
    title: str,
    article: list[dict],
    slug: str,
) -> GenerationResult:
    """Plan → render → assemble. Returns slots carrying PNG bytes + the markdown
    with body images injected. Each render is independent: a failed slot is
    dropped (logged), never fatal. If planning fails entirely, returns just the
    base markdown with no images."""
    sections = assemble_sections(article)
    base_md = render_markdown_with_images(sections, [])  # sections only, no images

    if not settings.blog_image_generation_enabled or not settings.openai_api_key:
        return GenerationResult(slots=[], markdown=base_md)

    words = count_words(sections)
    n_body = target_body_image_count(
        words,
        per_1000=settings.blog_images_per_1000_words,
        minimum=settings.blog_images_body_min,
        maximum=settings.blog_images_body_max,
    )

    try:
        plan = await plan_images(title, sections, n_body)
    except Exception as exc:  # noqa: BLE001 — planning is best-effort
        logger.warning("blog_image.plan_failed", extra={"slug": slug, "error": str(exc)})
        return GenerationResult(slots=[], markdown=base_md)

    slots = parse_plan(
        plan,
        sections=sections,
        slug=slug,
        n_body=n_body,
        style_suffix=settings.blog_image_style_suffix,
        hero_size=settings.blog_image_hero_size,
        body_size=settings.blog_image_body_size,
        base_path=settings.blog_image_repo_path,
    )

    rendered: list[ImageSlot] = []
    for slot in slots:
        try:
            slot.data = await render_image_bytes(slot.prompt, slot.size)
        except Exception as exc:  # noqa: BLE001 — per-image best-effort
            logger.warning(
                "blog_image.render_failed",
                extra={"slug": slug, "role": slot.role, "position": slot.position, "error": str(exc)},
            )
            continue
        slot.preview_url = upload_preview(slot.data, slot.repo_path)
        rendered.append(slot)

    body_rendered = [s for s in rendered if s.role == "body"]
    markdown = render_markdown_with_images(sections, body_rendered)
    return GenerationResult(slots=rendered, markdown=markdown)
