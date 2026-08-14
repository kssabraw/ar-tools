"""Website Builder — the deterministic half of the theme compiler.

A Claude Design export is a `.dc.html` prototype in a small custom DSL, rendered
client-side by a bundled React runtime. Most of turning one into an Astro theme
is *measurement*, not judgement, and measurement should not be done by a model:
counting how often `oklch(0.5 0.1 180)` appears is something a regex does
exactly and an LLM does approximately.

So this module extracts everything countable and structural, and hands the LLM a
much smaller job — naming and organising what was measured. Same division as the
page-structure scraper: the deterministic pass counts, the LLM pass names, and
the LLM never counts.

What it produces from one file:

* **screens** — each `sc-if` branch is one page of the site, so a single export
  yields the whole page-type set rather than "first page = layout".
* **collections** — each `sc-for` plus its sample array in `renderVals()` is a
  schema contract: the design is telling us which frontmatter fields it expects.
  The shape is kept and the sample rows are discarded.
* **image slots** — the export ships zero images, only labelled placeholders
  (`[ hero photo: plated balanced meal ]`). Those labels are the designer's own
  intent for each image, which is exactly what an image prompt wants.
* **token census** — styling is 100% inline `style="…"`, no classes and no
  stylesheet, so tokens are a frequency table over literal values.
* **routes** — the prototype's `state.screen` / `go*()` machinery exists only
  because a prototype cannot route. Astro has real routes, so the handlers are
  mapped to hrefs and the machinery is discarded.

Everything here is pure: one string in, one dataclass out.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, Optional

# A canvas/directions doc holds exploration turns — several design *options* per
# turn — not a design. An export can contain both, and compiling the wrong one
# produces a theme out of a mood board.
_CANVAS_RE = re.compile(r'<meta\s+name="design_doc_mode"\s+content="canvas"', re.I)

_SCRIPT_RE = re.compile(r'<script[^>]*type="text/x-dc"[^>]*>(.*?)</script>', re.S | re.I)
_HELMET_RE = re.compile(r"<helmet[^>]*>(.*?)</helmet>", re.S | re.I)
_STYLE_RE = re.compile(r"<style[^>]*>(.*?)</style>", re.S | re.I)
_FONT_HREF_RE = re.compile(r'fonts\.googleapis\.com/css2\?([^"\']+)')
_FAMILY_RE = re.compile(r"family=([^&:]+)")

_SC_IF_OPEN_RE = re.compile(r'<sc-if\s+value="\{\{\s*([A-Za-z_][\w]*)\s*\}\}"[^>]*>', re.I)
_SC_FOR_OPEN_RE = re.compile(
    r'<sc-for\s+list="\{\{\s*([A-Za-z_][\w]*)\s*\}\}"\s+as="([A-Za-z_][\w]*)"[^>]*>', re.I
)
_STYLE_ATTR_RE = re.compile(r'\sstyle="([^"]*)"', re.I)
_PLACEHOLDER_RE = re.compile(r"\[\s*([^\[\]]{3,80}?)\s*\]")
_HANDLER_RE = re.compile(r'onClick="\{\{\s*([A-Za-z_][\w.]*)\s*\}\}"')

# Colour literals, whatever property they appear in. Matching on the *value*
# rather than the property is what makes `border-bottom:1px solid #e3e9e6` yield
# its colour without teaching the census every shorthand.
_COLOR_RE = re.compile(
    r"(#[0-9a-fA-F]{3,8}\b"
    r"|oklch\([^)]*\)"
    r"|rgba?\([^)]*\)"
    r"|hsla?\([^)]*\))"
)
_LENGTH_RE = re.compile(r"^-?\d+(?:\.\d+)?(px|rem|em|%|vh|vw)$")

# Screen flags are named `isHome`, `isTopics`… Their page key is the rest,
# lowercased — the one naming convention the DSL actually guarantees.
_FLAG_PREFIX = "is"


@dataclass(frozen=True)
class Collection:
    """One `sc-for` binding and the frontmatter shape its sample rows imply."""

    name: str
    alias: str
    fields: tuple[str, ...]
    # How many placeholder rows the design previewed with. Design-time only —
    # it says nothing about how many entries a real site has.
    hint_count: Optional[int] = None


@dataclass(frozen=True)
class ImageSlot:
    """A labelled placeholder. The label is the designer's intent for the image."""

    label: str
    screen: Optional[str] = None
    # True when the label reads as a hero/banner rather than a card thumbnail.
    is_hero: bool = False
    # Set when the label came from a collection's sample rows rather than from
    # the page markup. Those are per-entry images the CONTENT supplies, not
    # slots the theme fills — but the label still says what kind of image the
    # field expects, which is what the generator wants.
    collection: Optional[str] = None

    @property
    def prompt_seed(self) -> str:
        """The label with its own framing words stripped, ready for a prompt."""
        text = re.sub(r"^\s*(hero\s+)?(photo|image|img)\s*:\s*", "", self.label, flags=re.I)
        return text.strip()


@dataclass(frozen=True)
class Screen:
    """One `sc-if` branch — one page of the site."""

    key: str
    flag: str
    html: str

    @property
    def is_empty(self) -> bool:
        return not self.html.strip()


@dataclass
class TokenCensus:
    """Frequency tables over the literal values the design actually uses.

    Ordered most-used first, because the most-repeated value is the one that
    deserves to become a token — the accent colour in the reference export
    appears 21 times and everything else is incidental.
    """

    colors: list[tuple[str, int]] = field(default_factory=list)
    font_families: list[tuple[str, int]] = field(default_factory=list)
    font_sizes: list[tuple[str, int]] = field(default_factory=list)
    font_weights: list[tuple[str, int]] = field(default_factory=list)
    radii: list[tuple[str, int]] = field(default_factory=list)
    spacing: list[tuple[str, int]] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.colors or self.font_families or self.font_sizes)


@dataclass
class Precompiled:
    """Everything measurable about one design file."""

    screens: list[Screen] = field(default_factory=list)
    collections: list[Collection] = field(default_factory=list)
    image_slots: list[ImageSlot] = field(default_factory=list)
    tokens: TokenCensus = field(default_factory=TokenCensus)
    fonts: list[str] = field(default_factory=list)
    global_css: str = ""
    # Prototype handler → the route it should become.
    routes: dict[str, str] = field(default_factory=dict)
    # Markup outside every sc-if branch: the header, footer and page shell that
    # every screen shares. This is what becomes Layout.astro.
    chrome_html: str = ""

    @property
    def screen_keys(self) -> list[str]:
        return [s.key for s in self.screens]


class PrecompileError(Exception):
    """Stable error code, not prose."""


# --------------------------------------------------------------------------
# Detection
# --------------------------------------------------------------------------


def is_canvas_doc(html: str) -> bool:
    """A canvas/directions doc is an exploration, not a design.

    Detected rather than guessed at: the export marks it explicitly, and the
    ingest step excludes it without asking. Compiling one would turn a page of
    design *options* into a theme.
    """
    return bool(_CANVAS_RE.search(html or ""))


def looks_like_design(html: str) -> bool:
    """A real design has a template root and at least one screen."""
    if not html or is_canvas_doc(html):
        return False
    return "<x-dc" in html.lower() and bool(_SC_IF_OPEN_RE.search(html))


def pick_design(files: dict[str, str]) -> tuple[Optional[str], list[str], list[str]]:
    """Choose the file to compile from a zip's contents.

    Returns `(chosen, designs, canvas_docs)`. With exactly one design the choice
    is made; with several the caller must ask rather than guess, because picking
    the wrong one silently produces a theme nobody designed.
    """
    designs = sorted(n for n, body in files.items() if looks_like_design(body))
    canvas = sorted(n for n, body in files.items() if is_canvas_doc(body or ""))
    return (designs[0] if len(designs) == 1 else None), designs, canvas


# --------------------------------------------------------------------------
# Structure
# --------------------------------------------------------------------------


def _matching_close(html: str, start: int, tag: str) -> int:
    """Index just past the `</tag>` that closes the element opening at `start`.

    Depth-counted rather than regex-matched: nesting the same tag is legal in
    the DSL, and a non-greedy regex would close the outer element on the inner
    element's tag.
    """
    open_re = re.compile(rf"<{tag}\b", re.I)
    close_re = re.compile(rf"</{tag}\s*>", re.I)
    depth = 0
    pos = start
    while pos < len(html):
        nxt_open = open_re.search(html, pos)
        nxt_close = close_re.search(html, pos)
        if not nxt_close:
            raise PrecompileError(f"unclosed_{tag}")
        if nxt_open and nxt_open.start() < nxt_close.start():
            depth += 1
            pos = nxt_open.end()
            continue
        depth -= 1
        pos = nxt_close.end()
        if depth == 0:
            return pos
    raise PrecompileError(f"unclosed_{tag}")


def screen_key(flag: str) -> str:
    """`isHome` → `home`, `isBlogPost` → `blog_post`."""
    body = flag[len(_FLAG_PREFIX):] if flag.startswith(_FLAG_PREFIX) else flag
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", body).lower()
    return snake or flag.lower()


def split_screens(html: str) -> tuple[list[Screen], str]:
    """Every `sc-if` branch, plus the markup left over once they are removed.

    The leftover is the shared chrome — header, footer, page shell — which is
    exactly what belongs in a layout rather than in a page template.
    """
    screens: list[Screen] = []
    remainder: list[str] = []
    pos = 0

    while True:
        match = _SC_IF_OPEN_RE.search(html, pos)
        if not match:
            remainder.append(html[pos:])
            break
        remainder.append(html[pos:match.start()])
        end = _matching_close(html, match.start(), "sc-if")
        inner = html[match.end():end]
        # Drop the closing tag the depth counter consumed.
        inner = re.sub(r"</sc-if\s*>\s*$", "", inner, flags=re.I)
        screens.append(Screen(key=screen_key(match.group(1)), flag=match.group(1), html=inner))
        pos = end

    return screens, "".join(remainder)


def parse_collections(html: str, script: str) -> list[Collection]:
    """Each `sc-for` and the field set its sample array carries.

    The sample rows are a schema contract, not content: `{cat, title, read,
    photo}` is the design telling us which frontmatter it will render. The shape
    is kept; every row is discarded.
    """
    out: list[Collection] = []
    seen: set[str] = set()

    for match in _SC_FOR_OPEN_RE.finditer(html):
        name, alias = match.group(1), match.group(2)
        if name in seen:
            continue
        seen.add(name)
        hint = re.search(r'hint-placeholder-count="(\d+)"', match.group(0))
        out.append(
            Collection(
                name=name,
                alias=alias,
                fields=_fields_for(name, alias, script, html),
                hint_count=int(hint.group(1)) if hint else None,
            )
        )
    return out


def _fields_for(name: str, alias: str, script: str, html: str) -> tuple[str, ...]:
    """Field names for one binding: the sample array first, the template second.

    Two sources because either can be incomplete — an array literal may be
    absent entirely, and the template only references the fields it happens to
    render. Their union is the honest answer.
    """
    fields: list[str] = []

    # `const latest = [ { cat:"…", title:"…" }, … ]`
    decl = re.search(
        rf"\b{re.escape(name)}\s*=\s*\[(.*?)\]\s*;", script or "", re.S
    )
    if decl:
        first_row = re.search(r"\{(.*?)\}", decl.group(1), re.S)
        if first_row:
            for key in re.finditer(r"([A-Za-z_][\w]*)\s*:", first_row.group(1)):
                if key.group(1) not in fields:
                    fields.append(key.group(1))

    # `{{ a.photo }}` inside the loop body.
    for used in re.finditer(rf"\{{\{{\s*{re.escape(alias)}\.([A-Za-z_][\w]*)", html):
        if used.group(1) not in fields:
            fields.append(used.group(1))

    # Handlers are prototype navigation, not content (see `routes`).
    return tuple(f for f in fields if f not in {"open", "onClick", "go"})


# --------------------------------------------------------------------------
# Imagery
# --------------------------------------------------------------------------

_HERO_HINT_RE = re.compile(r"\bhero\b|\bbanner\b|\bcover\b", re.I)
_IMAGE_HINT_RE = re.compile(r"\b(photo|image|img|illustration|portrait|shot)\b", re.I)


def harvest_image_slots(
    screens: Iterable[Screen], chrome: str = "", script: str = ""
) -> list[ImageSlot]:
    """Labelled placeholders, per screen.

    The export ships no images at all — every visual is a labelled string inside
    a striped-gradient block. Those labels are the one thing in the file that
    describes what each image should *be*, so they are captured per slot rather
    than discarded as sample text.
    """
    out: list[ImageSlot] = []
    seen: set[tuple[str, Optional[str]]] = set()

    def scan(text: str, screen: Optional[str], collection: Optional[str] = None) -> None:
        for match in _PLACEHOLDER_RE.finditer(text or ""):
            label = _unescape(match.group(1).strip())
            if not _IMAGE_HINT_RE.search(label):
                continue
            key = (label.lower(), screen)
            if key in seen:
                continue
            seen.add(key)
            out.append(
                ImageSlot(
                    label=label,
                    screen=screen,
                    is_hero=bool(_HERO_HINT_RE.search(label)),
                    collection=collection,
                )
            )

    scan(chrome, None)
    for screen in screens:
        scan(screen.html, screen.key)

    # The per-card labels live in the script's sample arrays, not the markup —
    # a screen-only scan finds the heroes and misses every thumbnail.
    for name, block in _sample_arrays(script).items():
        scan(block, None, collection=name)
    return out


# --------------------------------------------------------------------------
# Layout selection
#
# The token compile reskins; this carries *layout* intent one level up — which
# variant of a robust house component a screen should render — as pure data the
# page templates read (src/theme/layouts.json), never as generated markup. It is
# deterministic on purpose: image side is measured from the screen's own DOM
# order, the same "measure, don't guess" rule the token census follows, and
# every value is clamped to a fixed whitelist so the manifest can only ever name
# a layout the template implements (mirrors `validate_roles` for tokens).
# --------------------------------------------------------------------------

LAYOUT_MANIFEST_VERSION = 1

# In lockstep with src/lib/layouts.ts HERO_IMAGE_POSITIONS. A value one side
# knows and the other doesn't is exactly what the resolver's default guards
# against, but keeping the sets equal is what makes the guard rarely fire.
HERO_IMAGE_POSITIONS = ("right", "left", "none")
_HERO_IMAGE_DEFAULT = "right"

# A lead heading — where the screen's copy begins. Real prototypes emit <h1>/<h2>
# for the hero headline; DOM order of the hero image against it says which side
# the image is on.
_LEAD_HEADING_RE = re.compile(r"<h[12]\b", re.I)


def hero_image_position(screen_html: str) -> Optional[str]:
    """Which side a screen's hero image sits on, by DOM order vs the lead heading.

    Returns ``'left'``/``'right'`` when the screen carries a hero image slot, or
    ``None`` when it carries none. An omitted screen defaults to the house
    ``'right'`` in the resolver, so a screen without a measured hero never
    suppresses a hero the imagery step generates — the compiler only ever *moves*
    the image, it does not drop it. (``'none'`` stays a valid manifest value the
    template honours, reserved for a later, more confident text-only signal.)
    """
    html = screen_html or ""
    hero_off: Optional[int] = None
    for match in _PLACEHOLDER_RE.finditer(html):
        label = match.group(1)
        if _IMAGE_HINT_RE.search(label) and _HERO_HINT_RE.search(label):
            hero_off = match.start()
            break
    if hero_off is None:
        return None
    head = _LEAD_HEADING_RE.search(html)
    if head is None:
        return _HERO_IMAGE_DEFAULT
    return "left" if hero_off < head.start() else "right"


def _clamp_hero_image(value: Optional[str]) -> Optional[str]:
    """Whitelist guard: anything the template can't render is dropped (→ default)."""
    return value if value in HERO_IMAGE_POSITIONS else None


# Card-grid density — how many columns the design's own card grids use. The
# template's CardGridBase otherwise derives columns from a fixed min width and
# so never honours a design that is, say, deliberately 2-up and spacious. This
# is a theme-wide trait (a design's card density is one choice, not per screen),
# read from the design's declared `grid-template-columns`.
CARD_COLUMN_CHOICES = (2, 3, 4)

_GRID_TEMPLATE_COLUMNS_RE = re.compile(r"grid-template-columns\s*:\s*([^;\"']+)", re.I)
_GRID_REPEAT_RE = re.compile(r"repeat\(\s*(\d+)\s*,", re.I)


def _grid_column_count(value: str) -> Optional[int]:
    """Columns declared by one `grid-template-columns` value, if it is a card grid.

    Only *symmetric* grids count: card grids use equal tracks (`1fr 1fr 1fr`),
    while an asymmetric value (`1.35fr 1fr`) is a content/media split, not a card
    row, and must not be read as a column choice. Returns None outside 2–4.
    """
    text = value.strip()
    repeat = _GRID_REPEAT_RE.search(text)
    if repeat:
        count = int(repeat.group(1))
        return count if count in CARD_COLUMN_CHOICES else None
    tracks = text.split()
    if len(tracks) not in CARD_COLUMN_CHOICES:
        return None
    # Equal tracks only — one distinct track width means a real card grid.
    if len(set(tracks)) != 1:
        return None
    return len(tracks)


def card_grid_columns(pre: "Precompiled") -> Optional[int]:
    """The design's dominant card-grid column count, or None when unmeasured."""
    counts = [
        count
        for screen in pre.screens
        for match in _GRID_TEMPLATE_COLUMNS_RE.finditer(screen.html or "")
        if (count := _grid_column_count(match.group(1)))
    ]
    if not counts:
        return None
    return Counter(counts).most_common(1)[0][0]


def _clamp_columns(value: Optional[int]) -> Optional[int]:
    """Whitelist guard for the card-grid column choice."""
    return value if value in CARD_COLUMN_CHOICES else None


def build_layout_manifest(pre: "Precompiled") -> dict:
    """The ``layouts.json`` a compiled theme ships: per-screen + theme-wide selections.

    Pure: measurements in, the manifest dict out. A screen with no hero image
    slot, or a theme-wide trait the design didn't declare, is omitted rather
    than forced to a default, so the file stays a record of what was actually
    measured.
    """
    screens: dict[str, dict] = {}
    for screen in pre.screens:
        position = _clamp_hero_image(hero_image_position(screen.html))
        if position:
            screens[screen.key] = {"hero": {"image": position}}

    manifest: dict = {"version": LAYOUT_MANIFEST_VERSION, "screens": screens}

    columns = _clamp_columns(card_grid_columns(pre))
    if columns:
        manifest["components"] = {"cardColumns": columns}
    return manifest


def _sample_arrays(script: str) -> dict[str, str]:
    """Each `const name = [ … ]` block, so its placeholder labels stay attributed."""
    out: dict[str, str] = {}
    for match in re.finditer(r"\b(?:const|let|var)\s+([A-Za-z_][\w]*)\s*=\s*\[(.*?)\]\s*;", script or "", re.S):
        out[match.group(1)] = match.group(2)
    return out


def _unescape(text: str) -> str:
    return (
        text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    )


# --------------------------------------------------------------------------
# Tokens
# --------------------------------------------------------------------------


def _declarations(html: str) -> list[tuple[str, str]]:
    """Every `prop: value` from every inline style attribute."""
    out: list[tuple[str, str]] = []
    for attr in _STYLE_ATTR_RE.finditer(html or ""):
        for chunk in attr.group(1).split(";"):
            if ":" not in chunk:
                continue
            prop, _, value = chunk.partition(":")
            prop, value = prop.strip().lower(), value.strip()
            if prop and value:
                out.append((prop, value))
    return out


def _css_declarations(css: str) -> list[tuple[str, str]]:
    """Every `prop: value` from a stylesheet body, rules ignored.

    The helmet's global stylesheet is where a design states its *primary*
    typeface and page colours — `body{font-family:...}` — and those appear
    nowhere in the inline attributes. A census that reads only inline styles
    cannot see the font the whole site is set in.
    """
    out: list[tuple[str, str]] = []
    for block in re.finditer(r"\{([^{}]*)\}", css or ""):
        for chunk in block.group(1).split(";"):
            if ":" not in chunk:
                continue
            prop, _, value = chunk.partition(":")
            prop, value = prop.strip().lower(), value.strip()
            if prop and value:
                out.append((prop, value))
    return out


def census_styles(html: str, global_css: str = "") -> TokenCensus:
    """Frequency tables over the literal values the design uses.

    Styling is almost entirely inline, so that is where most tokens come from —
    but the helmet's global stylesheet carries the body font and the link
    colour, which are the most load-bearing values on the page and appear
    nowhere inline. Both sources feed one census.

    Colours are matched on the value so shorthand properties contribute without
    the census needing to know every shorthand's grammar.
    """
    decls = _declarations(html) + _css_declarations(global_css)
    colors: Counter[str] = Counter()
    families: Counter[str] = Counter()
    sizes: Counter[str] = Counter()
    weights: Counter[str] = Counter()
    radii: Counter[str] = Counter()
    spacing: Counter[str] = Counter()

    for prop, value in decls:
        for color in _COLOR_RE.findall(value):
            colors[_norm_color(color)] += 1
        if prop == "font-family":
            families[value.strip()] += 1
        elif prop == "font-size" and _LENGTH_RE.match(value):
            sizes[value] += 1
        elif prop == "font-weight":
            weights[value] += 1
        elif prop.startswith("border-radius") or prop == "border-radius":
            radii[value] += 1
        elif prop in {"gap", "row-gap", "column-gap"} or prop.startswith(("padding", "margin")):
            for token in value.split():
                if _LENGTH_RE.match(token) and token not in {"0", "0px"}:
                    spacing[token] += 1

    return TokenCensus(
        colors=colors.most_common(),
        font_families=families.most_common(),
        font_sizes=sizes.most_common(),
        font_weights=weights.most_common(),
        radii=radii.most_common(),
        spacing=spacing.most_common(),
    )


def _norm_color(value: str) -> str:
    """Lowercase, whitespace-collapsed, so one colour counts once."""
    return re.sub(r"\s+", " ", value.strip().lower())


def extract_fonts(html: str) -> list[str]:
    """Google Font families, for self-hosting at build.

    The theme must make no external request (the compiler's own post-check), so
    the families are captured here and the `<link>` is dropped rather than
    carried into the theme.
    """
    out: list[str] = []
    for href in _FONT_HREF_RE.finditer(html or ""):
        for family in _FAMILY_RE.finditer(href.group(1)):
            name = family.group(1).replace("+", " ").strip()
            if name and name not in out:
                out.append(name)
    return out


def extract_global_css(html: str) -> str:
    """The helmet's global `<style>` — reset, body font, link colours."""
    helmet = _HELMET_RE.search(html or "")
    if not helmet:
        return ""
    style = _STYLE_RE.search(helmet.group(1))
    return style.group(1).strip() if style else ""


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------


def route_map(screens: Iterable[Screen], overrides: Optional[dict[str, str]] = None) -> dict[str, str]:
    """`goTopics` → `/topics/`, for every screen the design actually has.

    The prototype's navigation exists only because a prototype cannot route:
    `state.screen` and the `go*()` handlers are a client-side switch. Astro has
    real routes, so every handler becomes an `<a href>` and the switch is
    discarded — one of the compiler's post-checks is that no `onClick` survives.
    """
    routes = {"goHome": "/"}
    for screen in screens:
        if screen.key == "home":
            continue
        handler = "go" + "".join(part.capitalize() for part in screen.key.split("_"))
        routes[handler] = f"/{screen.key.replace('_', '-')}/"
    routes.update(overrides or {})
    return routes


def strip_prototype_markup(html: str) -> str:
    """Remove the design-time scaffolding an Astro template must not carry."""
    out = re.sub(r"\shint-placeholder-[a-z]+=\"[^\"]*\"", "", html or "", flags=re.I)
    out = re.sub(r'\sonClick="\{\{[^}]*\}\}"', "", out, flags=re.I)
    out = re.sub(r"<script[^>]*type=\"text/x-dc\"[^>]*>.*?</script>", "", out, flags=re.S | re.I)
    return out


def residue(html: str) -> list[str]:
    """DSL leftovers in compiled output. Empty is the only passing result.

    The compiler's post-check: an `sc-if`, a `{{ }}` or an `onClick` surviving
    into a theme means a page that renders the prototype's scaffolding to a real
    visitor.
    """
    found: list[str] = []
    text = html or ""
    for pattern, label in (
        (r"<sc-if\b", "sc-if"),
        (r"<sc-for\b", "sc-for"),
        (r"\{\{", "interpolation"),
        (r"onClick=", "onClick"),
        (r"style-hover=", "style-hover"),
        (r"hint-placeholder-", "hint-placeholder"),
    ):
        if re.search(pattern, text, re.I):
            found.append(label)
    return found


# --------------------------------------------------------------------------
# The pass
# --------------------------------------------------------------------------


def precompile(html: str) -> Precompiled:
    """Measure one design file. Raises only when the input is not a design."""
    if not html or not html.strip():
        raise PrecompileError("empty_design_file")
    if is_canvas_doc(html):
        raise PrecompileError("design_doc_is_canvas")

    script_match = _SCRIPT_RE.search(html)
    script = script_match.group(1) if script_match else ""

    body = _SCRIPT_RE.sub("", html)
    global_css = extract_global_css(body)
    body_without_helmet = _HELMET_RE.sub("", body)

    screens, chrome = split_screens(body_without_helmet)
    if not screens:
        raise PrecompileError("no_screens_found")

    return Precompiled(
        screens=screens,
        collections=parse_collections(body_without_helmet, script),
        image_slots=harvest_image_slots(screens, chrome, script),
        tokens=census_styles(body_without_helmet, global_css),
        fonts=extract_fonts(html),
        global_css=global_css,
        routes=route_map(screens),
        chrome_html=chrome,
    )
