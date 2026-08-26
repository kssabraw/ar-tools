"""Website Builder — compiling a Claude Design export into a theme.

The template declares `src/theme/tokens.css` to be *the only file a theme swap
needs to touch*: every component reads its colours, type and spacing from those
custom properties. So the compile that actually reskins a site is the one that
writes that file, and this module writes it.

**The LLM's job is deliberately tiny.** `website_theme_precompile` has already
measured everything countable — which colours appear and how often, which font
families, which sizes, radii and spacing steps. What it cannot know is which
measured value plays which *role*: the most frequent colour might be the accent
or it might be white. That judgement is what the model is for.

And it cannot invent one. The model picks from the measured list, and
`validate_roles` rejects any value the census did not see — so a hallucinated
colour fails the compile instead of shipping as a site's brand. Extraction is
deterministic, naming is judged, and the two never swap places.

Component-level restructuring — turning each `sc-if` branch into its own Astro
template — is deliberately NOT here. The measured screens, collections and image
slots are stored on the theme record for that later phase; a token swap already
reskins every page, and it cannot break a build.
"""

from __future__ import annotations

import io
import json
import logging
import re
import zipfile
from dataclasses import dataclass
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import website_theme_fonts as fonts
from services.website_theme_precompile import (
    Precompiled,
    PrecompileError,
    build_layout_manifest,
    pick_design,
    precompile,
)

logger = logging.getLogger(__name__)


class ThemeError(Exception):
    """Stable error code, not prose."""


# The roles tokens.css needs filled. Each maps to a custom property the shipped
# components already read, so filling them reskins every page at once.
COLOR_ROLES: dict[str, str] = {
    "accent": "--color-accent",
    "accent_hover": "--color-accent-hover",
    "bg": "--color-bg",
    "surface": "--color-surface",
    "surface_muted": "--color-surface-muted",
    "text": "--color-text",
    "text_muted": "--color-text-muted",
    "text_subtle": "--color-text-subtle",
    "border": "--color-border",
    "border_strong": "--color-border-strong",
}

_ROLE_HELP: dict[str, str] = {
    "accent": "links, buttons and brand marks",
    "accent_hover": "the accent's darker hover state",
    "bg": "the page background behind everything",
    "surface": "cards and raised panels, usually white or near-white",
    "surface_muted": "subtly tinted panels, search fields, footers",
    "text": "body copy — the darkest ink",
    "text_muted": "secondary copy, captions",
    "text_subtle": "the faintest legible text, timestamps and hints",
    "border": "hairlines between sections and around cards",
    "border_strong": "a heavier rule where one is needed",
}

_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "colors": {
            "type": "object",
            "properties": {role: {"type": "string"} for role in COLOR_ROLES},
            "required": list(COLOR_ROLES),
            "additionalProperties": False,
        },
        "font_display": {"type": "string", "description": "Family for headings and brand marks."},
        "font_body": {"type": "string", "description": "Family for body copy."},
        "notes": {"type": "string", "description": "One sentence on the design's character."},
    },
    "required": ["colors", "font_display", "font_body"],
    "additionalProperties": False,
}

_SYSTEM = """You assign roles to design values that have already been measured.

You are given a frequency census taken from a real design file: every colour it
uses and how many times, its font families, and its type and spacing scales.

Your only job is to say which measured value plays which role.

Rules, and they are absolute:
- Every colour you return MUST be copied EXACTLY from the census list. Do not
  adjust, round, convert, or invent a colour. If no measured colour fits a role,
  pick the closest one that does — never write a new value.
- Frequency is evidence, not the answer. The most common colour in a light
  design is usually white or a border, not the accent. The accent is the one
  used on links, buttons and brand marks — often 10-25 occurrences, saturated,
  and distinct from the greys.
- Text colours run darkest to faintest: text, text_muted, text_subtle. Borders
  are the pale greys that are not backgrounds.
- accent_hover should be a darker variant of accent if one was measured;
  otherwise repeat the accent.
- Font families must be copied exactly from the measured list."""


@dataclass(frozen=True)
class ThemeTokens:
    """The assigned roles, after validation."""

    colors: dict[str, str]
    font_display: str
    font_body: str
    notes: str = ""


# --------------------------------------------------------------------------
# Zip ingest
# --------------------------------------------------------------------------


def safe_upload_name(filename: Optional[str]) -> str:
    """A storage-safe name for the uploaded export.

    Keeps the extension, because `read_upload` decides zip-vs-html from the
    bytes but a human reading the bucket decides from the name.
    """
    base = (filename or "design").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip("-.") or "design"
    return cleaned[:120]


def read_upload(data: bytes) -> dict[str, str]:
    """Design files from an uploaded export.

    Accepts a zip or a single `.dc.html`. Directory entries, the bundled
    `support.js` runtime and the `.thumbnail` are skipped — the runtime is the
    format's semantic authority but is not something we ship, because the whole
    point of compiling is to stop needing it.
    """
    if not data:
        raise ThemeError("empty_upload")

    if not data[:2] == b"PK":
        try:
            return {"design.dc.html": data.decode("utf-8", errors="replace")}
        except Exception as exc:  # pragma: no cover - decode with replace cannot raise
            raise ThemeError("unreadable_upload") from exc

    out: dict[str, str] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for info in archive.infolist():
                name = info.filename
                if info.is_dir() or name.startswith("__MACOSX/"):
                    continue
                if not name.lower().endswith((".html", ".htm")):
                    continue
                with archive.open(info) as handle:
                    out[name] = handle.read().decode("utf-8", errors="replace")
    except zipfile.BadZipFile as exc:
        raise ThemeError("bad_zip") from exc

    if not out:
        raise ThemeError("no_html_in_upload")
    return out


# --------------------------------------------------------------------------
# Pure: prompt, validation, emit
# --------------------------------------------------------------------------


def build_census_prompt(pre: Precompiled, *, max_colors: int = 24) -> str:
    """What the model is shown: measurements, never the design's markup.

    Deliberately not the HTML. The model's task is to label a frequency table,
    and handing it the whole file invites it to redesign rather than to name.
    """
    lines = ["MEASURED COLOURS (value — occurrences, most used first):"]
    for value, count in pre.tokens.colors[:max_colors]:
        lines.append(f"  {value} — {count}")

    lines.append("\nMEASURED FONT FAMILIES:")
    for value, count in pre.tokens.font_families[:8]:
        lines.append(f"  {value} — {count}")
    if pre.fonts:
        lines.append(f"  (web fonts loaded by the design: {', '.join(pre.fonts)})")

    if pre.global_css:
        lines.append(
            "\nGLOBAL STYLESHEET (sets the body and link colours — strong evidence "
            "for bg, text and accent):"
        )
        lines.append("  " + pre.global_css.strip().replace("\n", "\n  ")[:600])

    lines.append("\nROLES TO FILL:")
    for role, hint in _ROLE_HELP.items():
        lines.append(f"  {role}: {hint}")

    lines.append(f"\nThe design has {len(pre.screens)} screens: {', '.join(pre.screen_keys)}.")
    return "\n".join(lines)


def validate_roles(assigned: dict, pre: Precompiled) -> ThemeTokens:
    """Reject anything the census did not measure.

    This is what makes the compile safe to run unattended: the model cannot
    invent a brand colour, because a value that was never in the design fails
    here rather than shipping. A missing role is equally an error — silently
    defaulting one would produce a theme that is *partly* the design, which is
    harder to spot than one that is plainly wrong.
    """
    measured = {value for value, _ in pre.tokens.colors}
    colors_in = assigned.get("colors") or {}

    colors: dict[str, str] = {}
    for role in COLOR_ROLES:
        raw = (colors_in.get(role) or "").strip().lower()
        if not raw:
            raise ThemeError(f"token_role_missing:{role}")
        if raw not in measured:
            raise ThemeError(f"token_not_measured:{role}")
        colors[role] = raw

    # Fonts are held to the same bar as colours. This used to skip the check when
    # the census found no families at all (`if families and ...`), which meant the
    # one case where the model has nothing to copy from was the one case it was
    # free to invent — exactly backwards. A design with no measurable family is a
    # design we cannot honestly theme, so it fails the compile.
    families = {value for value, _ in pre.tokens.font_families}
    if not families:
        raise ThemeError("no_fonts_measured")
    display = (assigned.get("font_display") or "").strip()
    body = (assigned.get("font_body") or "").strip()
    for name, value in (("font_display", display), ("font_body", body)):
        if not value:
            raise ThemeError(f"token_role_missing:{name}")
        if value not in families:
            raise ThemeError(f"token_not_measured:{name}")

    return ThemeTokens(
        colors=colors,
        font_display=display,
        font_body=body,
        notes=(assigned.get("notes") or "").strip(),
    )


def _scale(
    values: list[tuple[str, int]],
    wanted: int,
    fallback: list[str],
    *,
    max_value: Optional[float] = None,
) -> list[str]:
    """A type or spacing scale from the measured steps, smallest to largest.

    Ordered by size rather than by frequency: a scale is a progression, and the
    most-used step is usually the middle of one. Short censuses fall back to the
    house defaults rather than inventing steps.

    `max_value` excludes outliers that are a different *kind* of value rather
    than a bigger one — a 999px pill radius is the most common radius in the
    reference design, and letting it into the scale makes every large-radius
    card a lozenge.
    """
    numeric: list[tuple[float, str]] = []
    for value, _ in values:
        match = re.match(r"^(-?\d+(?:\.\d+)?)(px|rem|em)$", value)
        if match:
            size = float(match.group(1))
            if max_value is not None and size >= max_value:
                continue
            numeric.append((size, value))
    numeric.sort()
    ordered = [value for _, value in numeric]
    if len(ordered) < wanted:
        return fallback
    # Even spread across the measured range, so the scale spans the design.
    step = (len(ordered) - 1) / (wanted - 1) if wanted > 1 else 0
    return [ordered[round(i * step)] for i in range(wanted)]


def render_tokens_css(tokens: ThemeTokens, pre: Precompiled, *, font_css: str = "") -> str:
    """The `tokens.css` a compiled theme ships.

    Every value here was measured in the design or is a house default the design
    had nothing to say about — the file never contains a value invented at
    compile time.

    `font_css` is the `@font-face` block for the families the compile managed to
    self-host. It goes first, because a `--font-display` naming a family nothing
    loads is a theme that renders in the system stack and looks like a choice.
    """
    text_sizes = _scale(
        pre.tokens.font_sizes, 8,
        ["0.78rem", "0.875rem", "1rem", "1.125rem", "1.3rem", "1.6rem", "2.1rem", "2.75rem"],
    )
    # 100px is well past any card corner and well below a pill.
    radii = _scale(pre.tokens.radii, 3, ["6px", "10px", "16px"], max_value=100)
    spacing = _scale(
        pre.tokens.spacing, 8,
        ["4px", "8px", "12px", "16px", "20px", "24px", "32px", "48px"],
    )
    size_names = ["xs", "sm", "base", "lg", "xl", "2xl", "3xl", "4xl"]

    lines = [
        "/*",
        " * Design tokens — compiled from an uploaded Claude Design export.",
        " *",
        " * Every colour and family below was MEASURED in that design; the compiler",
        " * refuses any value the design did not contain. Sizes and spacing are the",
        " * design's own steps where it had enough of them, and the house scale",
        " * where it did not.",
        " *",
        " * Regenerate by recompiling the design — do not hand-edit, or the next",
        " * compile will silently discard the edit.",
        " */",
    ]
    if font_css:
        lines += ["", font_css, ""]
    lines += [
        ":root {",
        "  /* Brand */",
    ]

    accent = tokens.colors["accent"]
    lines.append(f"  --color-accent: {accent};")
    lines.append(f"  --color-accent-hover: {tokens.colors['accent_hover']};")
    lines.append(f"  --color-accent-soft: color-mix(in srgb, {accent} 14%, transparent);")

    lines += [
        "",
        "  /* Surfaces */",
        f"  --color-bg: {tokens.colors['bg']};",
        f"  --color-surface: {tokens.colors['surface']};",
        f"  --color-surface-muted: {tokens.colors['surface_muted']};",
        "",
        "  /* Ink */",
        f"  --color-text: {tokens.colors['text']};",
        f"  --color-text-muted: {tokens.colors['text_muted']};",
        f"  --color-text-subtle: {tokens.colors['text_subtle']};",
        "",
        "  /* Lines */",
        f"  --color-border: {tokens.colors['border']};",
        f"  --color-border-strong: {tokens.colors['border_strong']};",
        "",
        "  /* Type */",
        f"  --font-display: {tokens.font_display};",
        f"  --font-body: {tokens.font_body};",
        "  --font-mono: ui-monospace, SFMono-Regular, Menlo, monospace;",
        "",
    ]
    for name, value in zip(size_names, text_sizes):
        lines.append(f"  --text-{name}: {value};")

    lines += [
        "",
        "  --leading-tight: 1.1;",
        "  --leading-snug: 1.35;",
        "  --leading-normal: 1.6;",
        "  --leading-relaxed: 1.72;",
        "",
        "  /* Shape */",
        f"  --radius-sm: {radii[0]};",
        f"  --radius-md: {radii[1]};",
        f"  --radius-lg: {radii[2]};",
        "  --radius-pill: 999px;",
        "",
        "  /* Space */",
    ]
    for i, value in enumerate(spacing, start=1):
        lines.append(f"  --space-{i}: {value};")

    lines += [
        "",
        "  --shadow-sm: 0 1px 2px rgb(0 0 0 / 0.04);",
        "  --shadow-md: 0 4px 16px rgb(0 0 0 / 0.06);",
        "  --wrap: 1120px;",
        "}",
        "",
    ]
    return "\n".join(lines)


def theme_record(pre: Precompiled, tokens: ThemeTokens, *, self_hosted_fonts: int = 0) -> dict:
    """What the theme row stores beyond the CSS.

    The screens, collections and image slots are kept even though this phase
    does not emit templates from them: they are the measured input the
    per-page-type compile needs, and re-measuring later would mean re-uploading
    a design the user has moved on from.
    """
    return {
        "colors": tokens.colors,
        "fontDisplay": tokens.font_display,
        "fontBody": tokens.font_body,
        "webFonts": pre.fonts,
        # How many font files the compile committed. Zero with a non-empty
        # webFonts list means the families are named but not loaded — worth
        # surfacing, because the site will render in the fallback stack.
        "selfHostedFonts": self_hosted_fonts,
        "notes": tokens.notes,
        "screens": pre.screen_keys,
        "collections": [
            {"name": c.name, "fields": list(c.fields), "previewCount": c.hint_count}
            for c in pre.collections
        ],
        "imageSlots": [
            {
                "label": s.label,
                "promptSeed": s.prompt_seed,
                "screen": s.screen,
                "collection": s.collection,
                "isHero": s.is_hero,
            }
            for s in pre.image_slots
        ],
        "routes": pre.routes,
    }


# --------------------------------------------------------------------------
# The compile
# --------------------------------------------------------------------------


async def assign_roles(pre: Precompiled) -> ThemeTokens:
    """One forced tool call: measured values in, role assignments out."""
    from services.report_llm import run_forced_tool

    assigned = await run_forced_tool(
        provider="anthropic",
        model=settings.website_theme_model,
        system=_SYSTEM,
        user=build_census_prompt(pre),
        tool_name="assign_theme_tokens",
        tool_description="Assign each measured design value to the role it plays.",
        input_schema=_TOOL_SCHEMA,
        max_tokens=1500,
        log_tag="website_theme",
    )
    return validate_roles(assigned or {}, pre)


async def compile_design(data: bytes) -> tuple[dict[str, bytes], dict, Precompiled]:
    """Upload bytes → `(files to commit, theme record, measurements)`.

    The files are `tokens.css` plus whatever font binaries the compile managed to
    self-host, keyed by their path under `src/theme/`.

    Raises `ThemeError` with a stable code on every failure worth telling the
    user about — an ambiguous zip, a canvas doc, a colour the design never had.
    """
    files = read_upload(data)
    chosen, designs, canvas = pick_design(files)

    if chosen is None:
        if not designs:
            raise ThemeError("no_design_in_upload" if not canvas else "upload_is_canvas_only")
        # Several real designs: ask rather than guess. Picking one silently
        # produces a theme nobody designed.
        raise ThemeError("multiple_designs:" + ",".join(designs))

    try:
        pre = precompile(files[chosen])
    except PrecompileError as exc:
        raise ThemeError(str(exc)) from exc

    tokens = await assign_roles(pre)

    # Best-effort by construction: a font CDN outage degrades the theme to
    # naming its families, it does not fail the compile.
    font_css, font_files = await fonts.fetch_font_bundle(
        pre.fonts or [tokens.font_display, tokens.font_body],
        fonts.wanted_weights(pre.tokens.font_weights),
    )

    # Layout intent as pure data — which house-component variant each screen
    # renders. Committed beside tokens.css and read by the template's resolver;
    # the house default omits it, so a screen we don't map renders as before.
    layout_manifest = build_layout_manifest(pre)

    out: dict[str, bytes] = {
        "tokens.css": render_tokens_css(tokens, pre, font_css=font_css).encode("utf-8"),
        "layouts.json": (json.dumps(layout_manifest, indent=2) + "\n").encode("utf-8"),
    }
    out.update(font_files)
    record = theme_record(pre, tokens, self_hosted_fonts=len(font_files))
    record["layouts"] = layout_manifest
    return out, record, pre


# The compiled files live under the theme id and are committed verbatim, so a
# site ships exactly the bytes that were reviewed rather than a recompile that
# might disagree with what someone approved.
BUILT_PREFIX = "built"
# Where the files land in a site repo. The template declares src/theme/ to be the
# only theme-specific directory, so a swap touches nothing else.
REPO_THEME_DIR = "src/theme"

_CONTENT_TYPES = {".css": "text/css", ".woff2": "font/woff2", ".json": "application/json"}


def built_path(theme_id: str, name: str) -> str:
    return f"{theme_id}/{BUILT_PREFIX}/{name}"


def store_built(theme_id: str, files: dict[str, bytes]) -> list[str]:
    """Put the compiled files in storage; return their names."""
    bucket = get_supabase().storage.from_(settings.website_theme_bucket)
    for name, data in files.items():
        suffix = name[name.rfind(".") :] if "." in name else ""
        bucket.upload(
            built_path(theme_id, name),
            data,
            {
                "content-type": _CONTENT_TYPES.get(suffix, "application/octet-stream"),
                "upsert": "true",
            },
        )
    return sorted(files)


def load_built(theme_id: str, names: list[str]) -> dict[str, bytes]:
    """Read the compiled files back for a commit."""
    bucket = get_supabase().storage.from_(settings.website_theme_bucket)
    return {name: bucket.download(built_path(theme_id, name)) for name in names}


def theme_files_for_repo(theme: dict) -> dict[str, bytes]:
    """The `src/theme/*` files a site repo needs for this theme.

    Returns empty for the house theme, which ships in the template already —
    committing a copy of it would produce a no-op commit and a pointless deploy.
    """
    if not theme or theme.get("source_kind") == "default":
        return {}
    names = (theme.get("tokens") or {}).get("builtFiles") or []
    if not names:
        return {}
    files = load_built(theme["id"], list(names))
    return {f"{REPO_THEME_DIR}/{name}": data for name, data in files.items()}


async def run_theme_compile_job(job: dict) -> None:
    """async_jobs handler for `website_theme_compile`."""
    payload = job.get("payload") or {}
    supabase = get_supabase()
    theme_id = payload.get("theme_id")

    try:
        rows = (
            supabase.table("website_themes").select("*").eq("id", theme_id).limit(1).execute()
        ).data
        if not rows:
            raise ThemeError("theme_not_found")

        source_ref = rows[0].get("source_ref")
        if not source_ref:
            raise ThemeError("theme_has_no_source")

        data = supabase.storage.from_(settings.website_theme_bucket).download(source_ref)
        files, record, _pre = await compile_design(data)
        record["builtFiles"] = store_built(theme_id, files)

        supabase.table("website_themes").update(
            {
                "status": "ready",
                "tokens": record,
                "storage_path": f"{theme_id}/{BUILT_PREFIX}",
                "error": None,
                "updated_at": "now()",
            }
        ).eq("id", theme_id).execute()

        supabase.table("async_jobs").update(
            {"status": "complete", "result": {"theme_id": theme_id}, "completed_at": "now()"}
        ).eq("id", job["id"]).execute()
        logger.info("website_theme.compiled", extra={"theme_id": theme_id})

    except Exception as exc:  # noqa: BLE001 — the failure belongs on the row
        detail = str(getattr(exc, "detail", None) or exc)
        logger.warning(
            "website_theme.compile_failed", extra={"job_id": job["id"], "error": detail}
        )
        if theme_id:
            supabase.table("website_themes").update(
                {"status": "failed", "error": detail[:500], "updated_at": "now()"}
            ).eq("id", theme_id).execute()
        supabase.table("async_jobs").update(
            {"status": "failed", "error": detail[:500], "completed_at": "now()"}
        ).eq("id", job["id"]).execute()


async def apply_theme_to_site(website: dict, theme: dict) -> Optional[str]:
    """Commit a compiled theme into a site's repo.

    Returns the commit sha, or None when there was nothing to commit — the site
    has no repo yet (provisioning will carry the theme in with its first commit),
    or the theme is the house default that already ships in the template.
    """
    repo = website.get("github_repo")
    files = theme_files_for_repo(theme)
    if not repo or not files:
        return None

    from services.github_publish import commit_files_to_github

    result = await commit_files_to_github(
        repo=repo,
        branch=settings.website_default_branch,
        token=settings.github_sites_token,
        files=files,
        message=f"Apply theme: {theme.get('name') or theme['id']}",
    )
    sha = result.get("commit_sha")
    # Through record_deploy, not a raw insert: it also enqueues the poll that
    # resolves the row. Inserting directly left the deploy at 'queued' until the
    # scheduler's next sweep, so a theme swap looked stuck next to a publish that
    # settles immediately.
    from services.website_deploy import record_deploy

    record_deploy(website_id=website["id"], commit_sha=sha, trigger="theme")
    return sha
