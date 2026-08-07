"""Website Builder — self-hosting the fonts a design uses.

A compiled theme that names `'Space Grotesk'` in `--font-display` and stops
there is not the design: no generated site loads that family, so every heading
silently falls back to the system stack. The theme looks *almost* right, which is
the worst way for it to be wrong — nobody files a bug about typography they
assume was the choice.

So the compile downloads the families the design declared and commits them into
the site repo. Self-hosted rather than a `<link>` to Google: a generated site
should make no third-party request at runtime, both because an external font is
the classic render-blocker and because the site outlives our access to whatever
CDN the design happened to reference.

Everything here is best-effort. A font CDN being unreachable must never fail a
theme compile — the theme degrades to naming the family, which is exactly the
behaviour we had before this module existed.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

_CSS_ENDPOINT = "https://fonts.googleapis.com/css2"

# Google serves woff2 only to browsers; a bare httpx UA gets the ttf fallback,
# which is roughly twice the bytes for the same glyphs.
_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Google splits a family into per-script subsets. Shipping all of them multiplies
# the bundle for scripts these sites do not publish in; `unicode-range` means a
# browser downloads only what a page actually uses, so the cost of dropping the
# rest is only that a stray Cyrillic character falls back.
DEFAULT_SUBSETS = ("latin", "latin-ext")

# What a site needs to render: body copy, its emphasis, and headings. Used when
# the design's own census is too thin to say.
FALLBACK_WEIGHTS = (400, 700)

# A ceiling on committed binaries, not on declared faces: several weights of a
# variable family share one file, so this bounds bytes rather than CSS rules.
_MAX_FILES = 8


@dataclass(frozen=True)
class FontFace:
    """One `@font-face` block from a Google Fonts stylesheet."""

    family: str
    weight: int
    style: str
    subset: str
    url: str
    unicode_range: str = ""

    @property
    def stem(self) -> str:
        return re.sub(r"[^a-z0-9]+", "-", self.family.lower()).strip("-")

    @property
    def filename(self) -> str:
        italic = "-italic" if self.style == "italic" else ""
        return f"{self.stem}-{self.weight}{italic}-{self.subset}.woff2"


def resolve_filenames(faces: Iterable[FontFace]) -> dict[str, str]:
    """One filename per distinct URL — `{url: filename}`.

    Both families in the reference design are **variable** fonts, and Google
    serves those as a single file per subset with one `@font-face` per requested
    weight all pointing at it. Naming by weight therefore downloads the same
    bytes three times under three names: the built site still worked (the
    bundler dedupes by content hash), which is exactly why this is worth fixing
    deliberately rather than leaving for someone to notice — the repo carried
    triplicate binaries and nothing complained.

    A URL shared across weights is named without one, because it is not a
    weight-400 file. A static family keeps the weight, because there its files
    genuinely differ.
    """
    by_url: dict[str, list[FontFace]] = {}
    for face in faces:
        by_url.setdefault(face.url, []).append(face)

    out: dict[str, str] = {}
    for url, group in by_url.items():
        first = group[0]
        if len({f.weight for f in group}) > 1:
            italic = "-italic" if first.style == "italic" else ""
            out[url] = f"{first.stem}{italic}-{first.subset}.woff2"
        else:
            out[url] = first.filename
    return out


def family_name(value: str) -> Optional[str]:
    """The family from a CSS font stack — `'Space Grotesk',sans-serif` → `Space Grotesk`.

    Generic families are not downloadable, so they come back as None rather than
    as a request for a font named `sans-serif`.
    """
    first = value.split(",")[0].strip().strip("'\"").strip()
    if not first:
        return None
    generic = {
        "sans-serif", "serif", "monospace", "cursive", "fantasy", "system-ui",
        "ui-sans-serif", "ui-serif", "ui-monospace", "ui-rounded", "inherit",
    }
    return None if first.lower() in generic else first


def wanted_weights(measured: Iterable[tuple[str, int]]) -> tuple[int, ...]:
    """The weights to fetch, taken from the design's own census.

    Measured rather than assumed: a design that only ever sets 500 and 800 gets
    500 and 800, and fetching a stock 400/700 pair would leave both of its real
    weights synthesised by the browser.
    """
    seen: set[int] = set()
    for value, _count in measured:
        text = str(value).strip().lower()
        named = {"normal": 400, "bold": 700, "lighter": 300, "bolder": 800}
        if text in named:
            seen.add(named[text])
        elif text.isdigit():
            number = int(text)
            if 100 <= number <= 900:
                # Google serves 100..900 in hundreds; anything else 404s the
                # whole stylesheet rather than just that weight. Half rounds up
                # (Python's round() would send 450 down to 400, which reads as a
                # bug at the call site even though it is a defensible tie-break).
                seen.add(min(900, int(number / 100 + 0.5) * 100))
    if not seen:
        return FALLBACK_WEIGHTS
    # Always keep a text weight — a design censused only at 700 (headings are
    # where inline font-weight tends to be set) would otherwise ship no body face.
    seen.add(400)
    return tuple(sorted(seen))


def css_url(family: str, weights: Iterable[int]) -> str:
    ordered = sorted(set(weights))
    axis = ";".join(str(w) for w in ordered)
    name = family.replace(" ", "+")
    return f"{_CSS_ENDPOINT}?family={name}:wght@{axis}&display=swap"


def parse_font_faces(css: str, *, subsets: Iterable[str] = DEFAULT_SUBSETS) -> list[FontFace]:
    """Parse Google's stylesheet into faces we can download.

    The subset name is only available as the comment above each block, which is
    why this is a scan over the raw text rather than a CSS parse.
    """
    keep = {s.lower() for s in subsets}
    faces: list[FontFace] = []
    subset = ""
    for chunk in re.split(r"(/\*[^*]*\*/)", css):
        comment = re.match(r"/\*\s*([a-z0-9\-]+)\s*\*/", chunk.strip(), re.I)
        if comment:
            subset = comment.group(1).lower()
            continue
        for block in re.findall(r"@font-face\s*\{([^}]*)\}", chunk):
            if keep and subset not in keep:
                continue
            url = re.search(r"url\((https://[^)]+\.woff2)\)", block)
            family = re.search(r"font-family:\s*'([^']+)'", block)
            weight = re.search(r"font-weight:\s*(\d+)", block)
            if not (url and family):
                continue
            style = "italic" if "font-style: italic" in block else "normal"
            unicode_range = re.search(r"unicode-range:\s*([^;]+);", block)
            faces.append(
                FontFace(
                    family=family.group(1),
                    weight=int(weight.group(1)) if weight else 400,
                    style=style,
                    subset=subset or "latin",
                    url=url.group(1),
                    unicode_range=(unicode_range.group(1).strip() if unicode_range else ""),
                )
            )
    return faces


def render_font_faces(
    faces: Iterable[FontFace],
    *,
    dir_name: str = "fonts",
    names: Optional[dict[str, str]] = None,
) -> str:
    """The `@font-face` CSS a compiled theme ships, pointing at committed files."""
    faces = list(faces)
    names = names if names is not None else resolve_filenames(faces)
    out: list[str] = []
    for face in faces:
        lines = [
            "@font-face {",
            f"  font-family: '{face.family}';",
            f"  font-style: {face.style};",
            f"  font-weight: {face.weight};",
            "  font-display: swap;",
            f"  src: url('./{dir_name}/{names[face.url]}') format('woff2');",
        ]
        if face.unicode_range:
            lines.append(f"  unicode-range: {face.unicode_range};")
        lines.append("}")
        out.append("\n".join(lines))
    return "\n".join(out)


async def fetch_font_bundle(
    families: Iterable[str],
    weights: Iterable[int] = FALLBACK_WEIGHTS,
    *,
    dir_name: str = "fonts",
) -> tuple[str, dict[str, bytes]]:
    """Download the families → `(@font-face CSS, {filename: woff2 bytes})`.

    Never raises. A family that cannot be fetched is simply absent from the
    bundle, and the theme falls back to naming it.
    """
    import httpx

    faces: list[FontFace] = []
    async with httpx.AsyncClient(timeout=20, headers={"User-Agent": _UA}) as http:
        for family in families:
            name = family_name(family) if "," in family else family
            if not name:
                continue
            try:
                resp = await http.get(css_url(name, weights))
                if resp.status_code != 200:
                    logger.info(
                        "website_theme_fonts.css_unavailable",
                        extra={"family": name, "http_status": resp.status_code},
                    )
                    continue
                faces.extend(parse_font_faces(resp.text))
            except Exception as exc:  # noqa: BLE001 — a font CDN is not load-bearing
                logger.info(
                    "website_theme_fonts.css_failed",
                    extra={"family": name, "error": str(exc)[:200]},
                )

        # One download per distinct URL. A variable family serves every weight
        # from one file, so downloading per face fetches the same bytes several
        # times and commits each copy.
        names = resolve_filenames(faces)
        urls = list(dict.fromkeys(f.url for f in faces))[:_MAX_FILES]

        files: dict[str, bytes] = {}
        for url in urls:
            try:
                resp = await http.get(url)
                if resp.status_code == 200 and resp.content:
                    files[f"{dir_name}/{names[url]}"] = resp.content
            except Exception as exc:  # noqa: BLE001
                logger.info(
                    "website_theme_fonts.download_failed",
                    extra={"font_file": names.get(url), "error": str(exc)[:200]},
                )

        # A @font-face pointing at a file we did not commit is a 404 on every
        # page load, so a face survives only if its bytes did.
        kept = [f for f in faces if f"{dir_name}/{names[f.url]}" in files]

    return render_font_faces(kept, dir_name=dir_name, names=names), files
