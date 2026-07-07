"""Geo-grid map image (Maps Module #5).

Renders a saved PNG of a per-keyword geo-grid scan: Google's static-map tile with
the numbered, color-coded rank pins composited on top — a faithful server-side
copy of the in-app map (`frontend/src/components/maps/visuals.tsx` + `rank.ts`),
so the exact map the team sees can be archived and dropped into reports.

The geometry helpers (`fit_zoom`, `cell_lat_lng`, `project_to_pixel`,
`rank_color`) are pure and mirror the frontend 1:1 — unit-tested against the same
values. The Pillow render + Google fetch + Supabase upload are the only I/O.

Best-effort throughout: no `GOOGLE_MAPS_API_KEY`, no grid, or a failed tile fetch
degrades gracefully (pins on a neutral background, or None) — it never sinks the
report job that calls it.
"""

from __future__ import annotations

import io
import logging
import math
from typing import Optional

from config import settings

logger = logging.getLogger(__name__)

# Logical square-map size (matches the frontend MAP_SIZE) requested at scale=2 for
# sharpness, so the actual pixel canvas is LOGICAL * SCALE.
LOGICAL = 480
SCALE = 2
PX = LOGICAL * SCALE

MAPS_IMAGE_BUCKET = "maps-images"

# Meters-per-pixel at the equator for web-Mercator zoom 0 (mirrors the frontend).
_MERCATOR_M_PER_PX_Z0 = 156543.03392


# ----------------------------------------------------------------------------
# Pure geometry + color (mirror frontend/src/components/maps/{visuals,rank}.ts)
# ----------------------------------------------------------------------------
def rank_color(rank: Optional[int]) -> tuple[int, int, int]:
    """RGB color band for a 1-based rank (grey = not ranked / null).

    Mirrors `rankColor` in rank.ts: #16a34a / #65a30d / #ca8a04 / #ea580c /
    #dc2626, grey #e5e7eb for null / < 1."""
    if rank is None or rank < 1:
        return (229, 231, 235)   # #e5e7eb
    if rank <= 3:
        return (22, 163, 74)     # #16a34a
    if rank <= 7:
        return (101, 163, 13)    # #65a30d
    if rank <= 10:
        return (202, 138, 4)     # #ca8a04
    if rank <= 15:
        return (234, 88, 22)     # #ea580c
    return (220, 38, 38)         # #dc2626


def fit_zoom(center_lat: float, n: int) -> int:
    """Largest integer Google zoom that frames an ~n-mile grid in ~90% of the
    image (floored so edge pins aren't clipped). Mirrors `fitZoom`."""
    target = (n * 1609.34) / (LOGICAL * 0.9)  # meters per logical px wanted
    z = math.log2((_MERCATOR_M_PER_PX_Z0 * math.cos(math.radians(center_lat))) / target)
    return max(1, min(16, math.floor(z)))


def cell_lat_lng(row: int, col: int, n: int, center_lat: float, center_lng: float) -> tuple[float, float]:
    """Lat/lng of an in-circle grid cell (1-mile spacing, row 0 = north).
    Mirrors `cellLatLng`."""
    c = (n - 1) / 2
    lat = center_lat + (c - row) * (1 / 69)
    lng = center_lng + (col - c) * (1 / (69 * math.cos(math.radians(center_lat))))
    return lat, lng


def project_to_pixel(lat: float, lng: float, center_lat: float, center_lng: float, zoom: int) -> tuple[float, float]:
    """Web-Mercator projection of a lat/lng to a pixel within a LOGICAL square map
    centered on (center_lat, center_lng) at `zoom`. Mirrors `projectToPixel`."""
    world_size = 256 * 2 ** zoom

    def px(lo: float) -> float:
        return ((lo + 180) / 360) * world_size

    def py(la: float) -> float:
        s = max(-0.9999, min(0.9999, math.sin(math.radians(la))))
        return (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * world_size

    x = px(lng) - px(center_lng) + LOGICAL / 2
    y = py(lat) - py(center_lat) + LOGICAL / 2
    return x, y


def _grid_cols(grid) -> int:
    """Widest row of a rank grid (0 when empty/invalid)."""
    if not isinstance(grid, list) or not grid:
        return 0
    return max((len(r) for r in grid if isinstance(r, list)), default=0)


def base_map_url(center_lat: float, center_lng: float, zoom: int) -> Optional[str]:
    """The marker-less Google Static Map URL centered on the scan (None with no
    API key). Mirrors `buildBaseMapUrl`."""
    key = settings.google_maps_api_key
    if not key or center_lat is None or center_lng is None:
        return None
    return (
        "https://maps.googleapis.com/maps/api/staticmap"
        f"?center={center_lat},{center_lng}&zoom={zoom}"
        f"&size={LOGICAL}x{LOGICAL}&scale={SCALE}&maptype=roadmap&key={key}"
    )


# ----------------------------------------------------------------------------
# Render (Pillow) — the only heavy I/O
# ----------------------------------------------------------------------------
async def _fetch_base_tile(url: str) -> Optional[bytes]:
    """GET the Google static-map PNG; None on any failure (→ neutral background)."""
    import httpx  # noqa: PLC0415 — lazy: keep the pure geometry helpers import-free

    try:
        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.get(url)
            resp.raise_for_status()
            return resp.content
    except Exception as exc:  # noqa: BLE001 — a dead tile must never sink the image
        logger.warning("maps_base_tile_fetch_failed", extra={"error": str(exc)})
        return None


def _load_font(size: int):
    """A bold TrueType font for crisp pin numbers (DejaVu is baked into the
    platform-api image), falling back to Pillow's bitmap default."""
    from PIL import ImageFont  # noqa: PLC0415

    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except Exception:  # noqa: BLE001
            continue
    return ImageFont.load_default()


def render_map_png(grid, center_lat: Optional[float], center_lng: Optional[float], base_tile: Optional[bytes]) -> Optional[bytes]:
    """Composite the numbered rank pins onto the base tile → PNG bytes.

    Pure aside from Pillow. `base_tile` is the pre-fetched Google static-map PNG
    (None → pins on a neutral background). Returns None when there's no usable
    grid or Pillow isn't available."""
    n = _grid_cols(grid)
    if not n or center_lat is None or center_lng is None:
        return None
    try:
        from PIL import Image, ImageDraw  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001 — sandbox without Pillow
        logger.warning("maps_image_pillow_unavailable", extra={"error": str(exc)})
        return None

    if base_tile:
        try:
            canvas = Image.open(io.BytesIO(base_tile)).convert("RGBA").resize((PX, PX))
        except Exception as exc:  # noqa: BLE001 — corrupt tile → neutral bg
            logger.warning("maps_image_base_decode_failed", extra={"error": str(exc)})
            canvas = Image.new("RGBA", (PX, PX), (241, 245, 249, 255))
    else:
        canvas = Image.new("RGBA", (PX, PX), (241, 245, 249, 255))  # slate-100

    draw = ImageDraw.Draw(canvas)
    zoom = fit_zoom(center_lat, n)
    c = (n - 1) / 2
    radius_sq = (n / 2) ** 2

    # Draw not-ranked dots first, then ranked pins, then the center pin, so higher-
    # value marks sit on top (matches the frontend z-order).
    ranked_pins: list[tuple[float, float, int]] = []
    center_pin: Optional[tuple[float, float, Optional[int]]] = None
    for row in range(n):
        for col in range(n):
            if (row - c) ** 2 + (col - c) ** 2 > radius_sq:
                continue
            lat, lng = cell_lat_lng(row, col, n, center_lat, center_lng)
            lx, ly = project_to_pixel(lat, lng, center_lat, center_lng, zoom)
            x, y = lx * SCALE, ly * SCALE
            grid_row = grid[row] if row < len(grid) and isinstance(grid[row], list) else []
            cell = grid_row[col] if col < len(grid_row) and grid_row[col] is not None else None
            rank = cell if isinstance(cell, int) and cell >= 1 else None
            is_center = float(row) == c and float(col) == c  # odd n → exact center
            if is_center:
                center_pin = (x, y, rank)
            elif rank is not None:
                ranked_pins.append((x, y, rank))
            else:
                _dot(draw, x, y, 6 * SCALE, (148, 163, 184))  # small grey dot

    for x, y, rank in ranked_pins:
        _pin(draw, x, y, 11 * SCALE, rank_color(rank), str(rank))
    if center_pin is not None:
        cx, cy, crank = center_pin
        # The business's own location: indigo halo ring, then the rank badge.
        _ring(draw, cx, cy, 14 * SCALE + 4, (79, 70, 229))  # #4f46e5
        _pin(draw, cx, cy, 14 * SCALE, rank_color(crank), str(crank) if crank else "")

    out = io.BytesIO()
    canvas.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()


def _dot(draw, x: float, y: float, d: float, rgb: tuple[int, int, int]) -> None:
    r = d / 2
    draw.ellipse([x - r, y - r, x + r, y + r], fill=rgb + (255,), outline=(255, 255, 255, 255), width=1)


def _ring(draw, x: float, y: float, r: float, rgb: tuple[int, int, int]) -> None:
    draw.ellipse([x - r, y - r, x + r, y + r], fill=rgb + (255,))


def _pin(draw, x: float, y: float, r: float, rgb: tuple[int, int, int], label: str) -> None:
    draw.ellipse([x - r, y - r, x + r, y + r], fill=rgb + (255,), outline=(255, 255, 255, 255), width=max(1, int(SCALE)))
    if label:
        font = _load_font(int(r * 1.1))
        try:
            bbox = draw.textbbox((0, 0), label, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            draw.text((x - tw / 2 - bbox[0], y - th / 2 - bbox[1]), label, fill=(255, 255, 255, 255), font=font)
        except Exception:  # noqa: BLE001 — text metrics can vary by Pillow/font
            draw.text((x, y), label, fill=(255, 255, 255, 255), font=font, anchor="mm")


# ----------------------------------------------------------------------------
# Storage
# ----------------------------------------------------------------------------
def store_map_image(supabase, client_id: str, scan_id: str, result_id: str, png: bytes) -> Optional[str]:
    """Upload the PNG to the public `maps-images` bucket and return its public URL.
    Best-effort — returns None on any storage failure."""
    path = f"{client_id}/{scan_id}/{result_id}.png"
    try:
        supabase.storage.from_(MAPS_IMAGE_BUCKET).upload(
            path, png, {"content-type": "image/png", "upsert": "true"}
        )
    except Exception as exc:  # noqa: BLE001 — a re-run may re-upload the same path
        logger.warning("maps_image_upload_failed", extra={"path": path, "error": str(exc)})
        return None
    try:
        res = supabase.storage.from_(MAPS_IMAGE_BUCKET).get_public_url(path)
        return res if isinstance(res, str) else (res.get("publicURL") or res.get("publicUrl") if isinstance(res, dict) else None)
    except Exception as exc:  # noqa: BLE001
        logger.warning("maps_image_public_url_failed", extra={"path": path, "error": str(exc)})
        return None


async def generate_and_store(
    supabase, client_id: str, scan_id: str, result_id: str, grid,
    center_lat: Optional[float], center_lng: Optional[float],
) -> Optional[str]:
    """Full path: fetch the base tile, render the pinned PNG, upload it, return the
    public URL. Best-effort — None when it can't be produced (no key, no grid,
    Pillow missing, upload failure)."""
    n = _grid_cols(grid)
    if not n or center_lat is None or center_lng is None:
        return None
    url = base_map_url(center_lat, center_lng, fit_zoom(center_lat, n))
    base_tile = await _fetch_base_tile(url) if url else None
    png = render_map_png(grid, center_lat, center_lng, base_tile)
    if not png:
        return None
    return store_map_image(supabase, client_id, scan_id, result_id, png)
