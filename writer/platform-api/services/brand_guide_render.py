"""Brand Guide Generator — Phase 3: PDF render + render profiles (PRD §4.7).

Turns a stored `brand_guides` row (the deterministic `visual_census`, the vision
`vibe_read`, and the grounded `synthesized` Proposed layer) into a portable,
client-facing **PDF** — deterministic assembly over the stored record, **the LLM
is NEVER called at render time** (§5.2: render is pure assembly over what earlier
phases already produced). The HTML is a self-contained `<!doctype html>` with an
inline print `<style>`; the homepage screenshot + logo are inlined as base64 data
URIs so the PDF is portable (no bucket signed-URLs / no live-host fetch needed to
view it).

**Render profiles (§4.7).** The same stored record renders two ways — the only
delta is the coherence/audit treatment:
  * `internal` — the blunt audit in full ("5 near-duplicate neutrals — leaking
    premium"): the deterministic coherence flags verbatim.
  * `client` — the identical findings reframed as forward-looking "opportunities
    to sharpen" (the LLM already reframed them into `coherence.narrative` +
    `section_gaps` at synthesis time), never diagnostic "your brand is broken".
Both ship; `storage_path`/`pdf_url` are per-profile (stored under `renders`, keyed
by profile; the top-level columns mirror the CLIENT profile — the deliverable).

**Trigger (§6).** For a NON-regulated client the generate job renders inline right
after synthesis (`brand_guide._finalize_guide` → here). For a regulated client the
generate job stops at `awaiting_signoff`; an admin/owning-staff approval enqueues
the separate `brand_guide_render` job (`run_brand_guide_render_job` → here), the
GBP-Profile-Editor "status + a 2nd job" pattern, since in-process jobs can't pause
mid-run.

Reuse (§7): `client_report.render_pdf` (WeasyPrint, lazy-imported — sandbox-safe),
`_store_pdf`/`_signed_url` (the `reports` bucket), and the Drive delivery via
`google_docs.resolve_drive_folder` / `upload_pdf`. We do NOT build a second PDF
renderer or a second Drive path.

Best-effort / degrade-never-fail (§5.4): a section with no data renders a muted
"not captured" line, never a blank; a render failure records `status='error'` +
an honest note on the row (the census/vibe/synthesized data is already persisted,
so nothing is lost — the guide is simply flagged for a re-render) and never
crashes the worker; a Drive-delivery failure is recorded, not raised. Every pure
HTML/section builder is unit-tested; WeasyPrint is mocked/lazy in tests.
"""

from __future__ import annotations

import base64
import html as _html
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from config import settings
from db.supabase_client import get_supabase
from services import brand_voice_service, icp_service

logger = logging.getLogger(__name__)

_BRAND_GUIDE_BUCKET = "brand-guides"  # where Phase-1 stored the page screenshots
PROFILES: tuple[str, ...] = ("internal", "client")


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------
def _esc(value: Any) -> str:
    return _html.escape("" if value is None else str(value))


def _pct(share: Any) -> str:
    return f"{round(share * 100)}%" if isinstance(share, (int, float)) else ""


def _muted(text: str) -> str:
    """A "not captured / not available" placeholder — never a blank section."""
    return f'<p class="na">{_esc(text)}</p>'


def _tuple3(val: Any) -> Optional[tuple]:
    if isinstance(val, (list, tuple)) and len(val) == 3:
        return tuple(val)
    return None


# ---------------------------------------------------------------------------
# Render context (pure over a client dict — the Documented voice/ICP layers)
# ---------------------------------------------------------------------------
def gather_render_context(client: dict) -> dict:
    """The client's owned Documented-layer assets for the render (PRD §4.4).

    Pure over the client dict — reads the canonical voice/ICP via the same
    resolvers synthesis used (`resolve_brand_guide_text` / `resolve_icp_text`, NOT
    the legacy `*_text` columns), the cached Voice & Audience Card, and the raw
    `brand_voice` dict (personality/tone) for the Documented voice block."""
    client = client if isinstance(client, dict) else {}
    voice_card = client.get("voice_card")
    card = voice_card.get("card") if isinstance(voice_card, dict) else None
    gbp = client.get("gbp") if isinstance(client.get("gbp"), dict) else {}
    bv = client.get("brand_voice") if isinstance(client.get("brand_voice"), dict) else {}
    return {
        "name": (client.get("name") or "").strip(),
        "website": (client.get("website_url") or "").strip(),
        "logo_url": (client.get("logo_url") or gbp.get("logo") or "").strip() or None,
        "brand_voice_text": brand_voice_service.resolve_brand_guide_text(client) or "",
        "icp_text": icp_service.resolve_icp_text(client) or "",
        "brand_voice": bv,
        "voice_card": card if isinstance(card, dict) else {},
        "differentiators": client.get("differentiators") if isinstance(client.get("differentiators"), list) else [],
    }


# ---------------------------------------------------------------------------
# Reusable render fragments
# ---------------------------------------------------------------------------
def _paras(text: str) -> str:
    """Render free-text (voice/ICP resolver output) as paragraphs, preserving
    blank-line separation and escaping."""
    text = (text or "").strip()
    if not text:
        return ""
    blocks = [b.strip() for b in text.split("\n\n") if b.strip()]
    return "".join(f"<p>{_esc(b).replace(chr(10), '<br/>')}</p>" for b in blocks)


def _chip_list(items: list, cls: str = "chip") -> str:
    out = [f'<span class="{cls}">{_esc(i)}</span>' for i in items if str(i or "").strip()]
    return f'<div class="chips">{"".join(out)}</div>' if out else ""


# ---------------------------------------------------------------------------
# Section 0 — Cover
# ---------------------------------------------------------------------------
def _cover(guide: dict, ctx: dict, *, logo_src: Optional[str], agency: str, client_facing: bool) -> str:
    synth = guide.get("synthesized") or {}
    tagline = (synth.get("tagline") or "").strip()
    logo_html = f'<img class="logo" src="{_esc(logo_src)}"/>' if logo_src else ""
    version = guide.get("version")
    generated = _fmt_date(guide.get("generated_at") or guide.get("created_at"))
    kind = "Brand Guide" if client_facing else "Brand Guide · Internal Audit"
    return (
        '<header class="cover">'
        f"{logo_html}"
        f"<h1>{_esc(ctx.get('name') or 'Brand')}</h1>"
        f'<div class="subtitle">{_esc(kind)}</div>'
        + (f'<div class="tagline">{_esc(tagline)}</div>' if tagline else "")
        + f'<div class="meta">Prepared by {_esc(agency)}'
        + (f" · v{_esc(version)}" if version else "")
        + (f" · {_esc(generated)}" if generated else "")
        + "</div>"
        "</header>"
    )


def _fmt_date(raw: Any) -> str:
    if not raw:
        return ""
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date().isoformat()
    except (ValueError, TypeError):
        return str(raw)[:10]


# ---------------------------------------------------------------------------
# Section 1 — Brand Foundation
# ---------------------------------------------------------------------------
def _section_foundation(guide: dict, ctx: dict) -> str:
    synth = guide.get("synthesized") or {}
    bv = ctx.get("brand_voice") or {}

    # Documented
    doc_parts: list[str] = []
    overview = ctx.get("brand_voice_text") or ""
    if overview:
        doc_parts.append(_paras(overview[:2000]))
    themes = bv.get("messaging_themes")
    if isinstance(themes, list) and themes:
        doc_parts.append("<h4>Themes</h4>" + _chip_list(themes))
    diffs = ctx.get("differentiators") or []
    diff_lines = []
    for d in diffs:
        if isinstance(d, dict) and (d.get("claim") or "").strip():
            mech = (d.get("mechanism") or "").strip()
            diff_lines.append(_esc(d["claim"]) + (f" <span class='dim'>— {_esc(mech)}</span>" if mech else ""))
    if diff_lines:
        doc_parts.append("<h4>Differentiators</h4><ul>" + "".join(f"<li>{x}</li>" for x in diff_lines) + "</ul>")
    documented = "".join(doc_parts) or _muted("No brand-voice or differentiator assets on file for this client.")

    # Proposed
    prop_parts: list[str] = []
    if synth.get("mission"):
        prop_parts.append(f"<h4>Mission / promise</h4><p>{_esc(synth['mission'])}</p>")
    if synth.get("positioning_statement"):
        prop_parts.append(f"<h4>Positioning</h4><p>{_esc(synth['positioning_statement'])}</p>")
    if synth.get("tagline"):
        opts = [o for o in (synth.get("tagline_options") or []) if o and o != synth.get("tagline")]
        prop_parts.append(
            f"<h4>Tagline</h4><p class='tagline-line'>{_esc(synth['tagline'])}</p>"
            + (f"<p class='dim'>Alternates: {_esc(' · '.join(opts))}</p>" if opts else "")
        )
    proposed = "".join(prop_parts) or _muted("No proposed foundation synthesized (synthesis was unavailable).")

    return _dual_section("Brand Foundation", documented, proposed)


# ---------------------------------------------------------------------------
# Section 2 — Audience (ICP)
# ---------------------------------------------------------------------------
def _section_audience(ctx: dict) -> str:
    icp = ctx.get("icp_text") or ""
    body = _paras(icp[:4000]) if icp else _muted(
        "No audience (ICP) profile on file — add or scan the client's ICP to enrich this section."
    )
    return f'<section class="sec"><h2>Audience</h2><div class="doc">{body}</div></section>'


# ---------------------------------------------------------------------------
# Section 3 — Voice & Messaging
# ---------------------------------------------------------------------------
def _section_voice(guide: dict, ctx: dict) -> str:
    synth = guide.get("synthesized") or {}
    bv = ctx.get("brand_voice") or {}
    card = ctx.get("voice_card") or {}

    # Documented
    doc_parts: list[str] = []
    rows: list[tuple[str, Any]] = [
        ("Personality", bv.get("personality")),
        ("Tone", bv.get("tone")),
        ("Writing style", bv.get("writing_style")),
    ]
    dl = "".join(
        f"<dt>{_esc(label)}</dt><dd>{_esc(_flatten(val))}</dd>" for label, val in rows if _flatten(val)
    )
    if dl:
        doc_parts.append(f"<dl class='kv'>{dl}</dl>")
    must = card.get("must_use_terms") if isinstance(card, dict) else None
    never = card.get("never_use_terms") if isinstance(card, dict) else None
    if isinstance(must, list) and must:
        doc_parts.append("<h4>Use</h4>" + _chip_list(must, "chip ok"))
    if isinstance(never, list) and never:
        doc_parts.append("<h4>Avoid</h4>" + _chip_list(never, "chip no"))
    documented = "".join(doc_parts) or _muted("No distilled brand voice on file for this client.")

    # Proposed — worked examples, we-say/we-don't, key messages, boilerplate
    prop_parts: list[str] = []
    ve = synth.get("voice_examples") or {}
    ex_rows = [
        ("Headline", ve.get("headline")), ("CTA", ve.get("cta")),
        ("Product blurb", ve.get("product_blurb")), ("Email opener", ve.get("email_opener")),
    ]
    ex = "".join(f"<dt>{_esc(k)}</dt><dd>{_esc(v)}</dd>" for k, v in ex_rows if v)
    if ex:
        prop_parts.append(f"<h4>Worked examples</h4><dl class='kv'>{ex}</dl>")
    wswd = synth.get("we_say_we_dont") or []
    if wswd:
        rows_html = "".join(
            f"<tr><td>{_esc(r.get('we_say'))}</td><td class='dim'>{_esc(r.get('we_dont'))}</td></tr>"
            for r in wswd if isinstance(r, dict)
        )
        prop_parts.append(
            "<h4>We say / we don't</h4><table class='wswd'><thead><tr>"
            "<th>We say</th><th>We don't</th></tr></thead><tbody>" + rows_html + "</tbody></table>"
        )
    km = synth.get("key_messages") or []
    if km:
        prop_parts.append("<h4>Key messages</h4><ul>" + "".join(f"<li>{_esc(m)}</li>" for m in km) + "</ul>")
    bp = synth.get("boilerplate") or {}
    if isinstance(bp, dict) and (bp.get("short") or bp.get("long")):
        prop_parts.append("<h4>Boilerplate</h4>")
        if bp.get("short"):
            prop_parts.append(f"<p><span class='dim'>Short —</span> {_esc(bp['short'])}</p>")
        if bp.get("long"):
            prop_parts.append(f"<p><span class='dim'>Long —</span> {_esc(bp['long'])}</p>")
    proposed = "".join(prop_parts) or _muted("No proposed messaging synthesized (synthesis was unavailable).")

    return _dual_section("Voice & Messaging", documented, proposed)


def _flatten(val: Any) -> str:
    if isinstance(val, (list, tuple)):
        return ", ".join(str(v).strip() for v in val if str(v or "").strip())
    return str(val).strip() if val else ""


# ---------------------------------------------------------------------------
# Section 4 — Logo
# ---------------------------------------------------------------------------
_CLEARSPACE_RULE = (
    "Keep clear space around the logo equal to at least the height of its dominant "
    "letterform / mark on every side — never crowd it with text, imagery, or edges."
)
_MINSIZE_RULE = (
    "Do not reproduce the logo below ~24px tall on screen or ~10mm in print; below "
    "that, use the mark/monogram alone rather than the full lockup."
)


def _section_logo(guide: dict, *, logo_src: Optional[str]) -> str:
    census = guide.get("visual_census") or {}
    cands = [c for c in (census.get("logo_candidates") or []) if isinstance(c, dict)]

    doc_parts: list[str] = []
    if logo_src:
        doc_parts.append(f'<div class="logo-frame"><img src="{_esc(logo_src)}"/></div>')
    if cands:
        rows = "".join(
            f"<tr><td class='trunc'>{_esc(c.get('url'))}</td><td>{_esc(c.get('source'))}</td>"
            f"<td class='num'>{_esc(c.get('score'))}</td></tr>"
            for c in cands[:6]
        )
        doc_parts.append(
            "<p class='dim'>Detected logo candidates (highest-confidence first):</p>"
            "<table class='cands'><thead><tr><th>URL</th><th>Source</th><th class='num'>Score</th>"
            f"</tr></thead><tbody>{rows}</tbody></table>"
        )
    documented = "".join(doc_parts) or _muted("No logo captured — upload a logo or connect the GBP listing.")

    proposed = (
        f"<h4>Clear space</h4><p>{_esc(_CLEARSPACE_RULE)}</p>"
        f"<h4>Minimum size</h4><p>{_esc(_MINSIZE_RULE)}</p>"
        "<h4>Do / don't</h4><ul>"
        "<li>Do keep the original proportions and approved colourways.</li>"
        "<li>Don't stretch, recolour, add effects, or place it on a low-contrast background.</li>"
        "</ul>"
    )
    return _dual_section("Logo", documented, proposed)


# ---------------------------------------------------------------------------
# Section 5 — Aesthetic & Art Direction (the profile delta lives here)
# ---------------------------------------------------------------------------
def _mood_bar(key: str, value: int) -> str:
    lo, hi = key.replace("_", " ↔ ").split(" ↔ ", 1) if "_" in key else (key, "")
    pos = max(0, min(100, int(value)))
    return (
        f'<div class="axis"><span class="axl">{_esc(lo)}</span>'
        f'<span class="axtrack"><span class="axdot" style="left:{pos}%"></span></span>'
        f'<span class="axr">{_esc(hi)}</span></div>'
    )


def _section_aesthetic(guide: dict, *, client_facing: bool) -> str:
    vibe = guide.get("vibe_read") or {}
    synth = guide.get("synthesized") or {}

    # Documented — the felt vibe read
    doc_parts: list[str] = []
    descriptors = [d for d in (vibe.get("aesthetic_descriptors") or []) if isinstance(d, dict)]
    if descriptors:
        items = "".join(
            f"<li><strong>{_esc(d.get('descriptor'))}</strong>"
            f"<span class='dim'> — {_esc(d.get('evidence'))}</span></li>"
            for d in descriptors
        )
        doc_parts.append(f"<h4>Aesthetic</h4><ul class='aesthetic'>{items}</ul>")
    axes = vibe.get("mood_axes") if isinstance(vibe.get("mood_axes"), dict) else {}
    if axes:
        bars = "".join(_mood_bar(k, v) for k, v in axes.items() if isinstance(v, int))
        if bars:
            doc_parts.append(f"<h4>Mood</h4><div class='axes'>{bars}</div>")
    char = vibe.get("character") if isinstance(vibe.get("character"), dict) else {}
    if char:
        rows = "".join(
            f"<dt>{_esc(k.replace('_', ' '))}</dt><dd>{_esc(v)}</dd>" for k, v in char.items() if v
        )
        if rows:
            doc_parts.append(f"<h4>Character</h4><dl class='kv'>{rows}</dl>")
    documented = "".join(doc_parts) or _muted(
        "No aesthetic read captured — the homepage screenshot was unavailable, so the felt "
        "visual layer was skipped (the guide rests on the measured tokens + voice/ICP)."
    )

    # Proposed — the coherence treatment (THE profile delta, §4.7)
    coherence = synth.get("coherence") if isinstance(synth.get("coherence"), dict) else {}
    flags = [f for f in (coherence.get("flags") or []) if isinstance(f, dict)]
    narrative = (coherence.get("narrative") or "").strip()
    gaps = [g for g in (synth.get("section_gaps") or []) if isinstance(g, dict)]

    prop_parts: list[str] = []
    if client_facing:
        # Client: reframed opportunities — the narrative + section gaps, no blunt flags.
        prop_parts.append("<h4>Opportunities to sharpen</h4>")
        if narrative:
            prop_parts.append(f"<p>{_esc(narrative)}</p>")
        if gaps:
            prop_parts.append(
                "<ul>" + "".join(
                    f"<li><strong>{_esc(g.get('section'))}</strong> — {_esc(g.get('gap'))}</li>"
                    if g.get("section") else f"<li>{_esc(g.get('gap'))}</li>"
                    for g in gaps
                ) + "</ul>"
            )
        if not narrative and not gaps:
            prop_parts.append(_muted("The measured details and the felt aesthetic read as consistent — no gaps flagged."))
    else:
        # Internal: the blunt audit — the deterministic flags verbatim.
        prop_parts.append("<h4>Coherence audit — where the brand is leaking</h4>")
        if flags:
            prop_parts.append(
                "<ul class='flags'>" + "".join(
                    f"<li class='flag-{_esc(f.get('severity') or 'gap')}'>"
                    f"<strong>{_esc(f.get('title'))}</strong>"
                    f"<span class='dim'> — {_esc(f.get('detail'))}</span></li>"
                    for f in flags
                ) + "</ul>"
            )
        else:
            prop_parts.append(_muted("No coherence gaps detected — the palette, type scale and fonts read as disciplined."))
        if narrative:
            prop_parts.append(f"<p class='dim'>{_esc(narrative)}</p>")
        if gaps:
            prop_parts.append(
                "<h4>Per-section gaps</h4><ul>" + "".join(
                    f"<li><strong>{_esc(g.get('section'))}</strong> — {_esc(g.get('gap'))}</li>"
                    if g.get("section") else f"<li>{_esc(g.get('gap'))}</li>"
                    for g in gaps
                ) + "</ul>"
            )
    proposed = "".join(prop_parts)

    return _dual_section("Aesthetic & Art Direction", documented, proposed, proposed_label="Direction")


# ---------------------------------------------------------------------------
# Section 6 — Color
# ---------------------------------------------------------------------------
def _swatch_chip(hexval: str) -> str:
    return f'<span class="sw" style="background:{_esc(hexval)}"></span>' if hexval else ""


def _section_color(guide: dict) -> str:
    census = guide.get("visual_census") or {}
    colors = [c for c in (census.get("colors") or []) if isinstance(c, dict)]
    synth = guide.get("synthesized") or {}
    scolor = synth.get("color") if isinstance(synth.get("color"), dict) else {}

    # Documented — the real measured palette
    if colors:
        rows = ""
        for c in colors:
            rgb = _tuple3(c.get("rgb"))
            cmyk = c.get("cmyk") if isinstance(c.get("cmyk"), (list, tuple)) else None
            hsl = _tuple3(c.get("hsl"))
            rows += (
                f"<tr><td>{_swatch_chip(c.get('hex'))}</td>"
                f"<td class='mono'>{_esc(c.get('hex'))}</td>"
                f"<td class='mono'>{_esc('rgb(' + ', '.join(map(str, rgb)) + ')') if rgb else '—'}</td>"
                f"<td class='mono'>{_esc('cmyk(' + ', '.join(map(str, cmyk)) + ')') if cmyk else '—'}</td>"
                f"<td class='mono'>{_esc('hsl(' + ', '.join(map(str, hsl)) + ')') if hsl else '—'}</td>"
                f"<td class='num'>{_esc(_pct(c.get('share')))}</td></tr>"
            )
        documented = (
            "<table class='palette'><thead><tr><th></th><th>Hex</th><th>RGB</th>"
            "<th>CMYK</th><th>HSL</th><th class='num'>Share</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
            "<p class='dim'>Dominance is the colour's share of the rendered homepage.</p>"
        )
    else:
        documented = _muted(
            "No palette recovered — the site had no readable screenshot or CSS colours "
            "(a client with no live site gets a prescriptive palette in the Proposed layer)."
        )

    # Proposed — named/roled swatches, 60/30/10, WCAG pairings
    prop_parts: list[str] = []
    swatches = [s for s in (scolor.get("swatches") or []) if isinstance(s, dict)]
    if swatches:
        cells = "".join(
            f"<div class='pswatch'>{_swatch_chip(s.get('hex'))}"
            f"<div class='psn'>{_esc(s.get('name') or s.get('hex'))}</div>"
            f"<div class='psr'>{_esc(s.get('role') or '')}</div>"
            f"<div class='mono psh'>{_esc(s.get('hex'))}</div></div>"
            for s in swatches
        )
        prop_parts.append(f"<h4>Named palette</h4><div class='pswatches'>{cells}</div>")
    ur = scolor.get("usage_ratios") if isinstance(scolor.get("usage_ratios"), dict) else {}
    roles = ur.get("roles") if isinstance(ur.get("roles"), dict) else {}
    if roles:
        role_rows = "".join(
            f"<li><strong>{_esc(role)}</strong> "
            f"<span class='dim'>{_esc(info.get('share'))}</span> "
            + "".join(_swatch_chip(h) for h in (info.get("hexes") or []))
            + "</li>"
            for role, info in roles.items() if isinstance(info, dict)
        )
        prop_parts.append(f"<h4>Usage (60 / 30 / 10)</h4><ul class='usage'>{role_rows}</ul>")
    if scolor.get("usage_narrative"):
        prop_parts.append(f"<p>{_esc(scolor['usage_narrative'])}</p>")
    pairings = [p for p in (scolor.get("pairings") or []) if isinstance(p, dict)]
    if pairings:
        prows = "".join(
            f"<tr><td>{_swatch_chip(p.get('background'))}</td>"
            f"<td class='mono'>{_esc(p.get('text'))} on {_esc(p.get('background'))}</td>"
            f"<td class='num'>{_esc(p.get('ratio'))}:1</td>"
            f"<td>{_esc(p.get('level'))}{'' if p.get('passes_body', True) else ' ⚠'}</td></tr>"
            for p in pairings
        )
        prop_parts.append(
            "<h4>Accessible pairings (WCAG)</h4><table class='pair'><thead><tr>"
            "<th></th><th>Text on background</th><th class='num'>Ratio</th><th>Level</th>"
            f"</tr></thead><tbody>{prows}</tbody></table>"
        )
    proposed = "".join(prop_parts) or _muted("No proposed colour system synthesized (synthesis was unavailable).")

    return _dual_section("Color", documented, proposed)


# ---------------------------------------------------------------------------
# Section 7 — Typography
# ---------------------------------------------------------------------------
def _section_typography(guide: dict) -> str:
    census = guide.get("visual_census") or {}
    fonts = [f for f in (census.get("fonts") or []) if isinstance(f, dict)]
    steps = [t for t in (census.get("type_scale") or []) if isinstance(t, dict)]
    synth = guide.get("synthesized") or {}
    named = [t for t in (synth.get("type_scale") or []) if isinstance(t, dict)]

    doc_parts: list[str] = []
    if fonts:
        items = "".join(
            f"<li><strong>{_esc(f.get('name'))}</strong>"
            + (" <span class='tag'>Google Fonts</span>" if f.get("google") else "")
            + "</li>"
            for f in fonts if f.get("name")
        )
        doc_parts.append(f"<h4>Typefaces</h4><ul class='fonts'>{items}</ul>")
    if steps:
        sizes = " · ".join(f"{_esc(s.get('px'))}px" for s in steps if s.get("px") is not None)
        doc_parts.append(f"<h4>Measured sizes (largest → smallest)</h4><p class='mono'>{sizes}</p>")
    documented = "".join(doc_parts) or _muted(
        "No typefaces recovered from the site's inline/embedded CSS (fonts may be set via an external stylesheet)."
    )

    if named:
        rows = "".join(
            f"<tr><td><strong>{_esc(t.get('name'))}</strong></td>"
            f"<td class='mono'>{_esc(t.get('px'))}px</td>"
            f"<td class='dim'>{_esc(t.get('usage'))}</td></tr>"
            for t in named
        )
        proposed = (
            "<h4>Type scale</h4><table class='scale'><thead><tr><th>Step</th>"
            f"<th>Size</th><th>Usage</th></tr></thead><tbody>{rows}</tbody></table>"
        )
    else:
        proposed = _muted("No named type scale synthesized (synthesis was unavailable).")

    return _dual_section("Typography", documented, proposed)


# ---------------------------------------------------------------------------
# Section 8 — Imagery & Iconography
# ---------------------------------------------------------------------------
def _section_imagery(guide: dict) -> str:
    synth = guide.get("synthesized") or {}
    vibe = guide.get("vibe_read") or {}
    img = synth.get("imagery_direction") if isinstance(synth.get("imagery_direction"), dict) else {}

    doc_parts: list[str] = []
    style = (vibe.get("character") or {}).get("imagery_style") if isinstance(vibe.get("character"), dict) else None
    if style:
        doc_parts.append(f"<p><span class='dim'>Observed —</span> {_esc(style)}</p>")
    documented = "".join(doc_parts) or _muted("No imagery observed from the captured pages.")

    prop_parts: list[str] = []
    rows = [
        ("Subjects", img.get("subjects")), ("Lighting", img.get("lighting")),
        ("Treatment", img.get("treatment")), ("Stock vs custom", img.get("stock_vs_custom")),
    ]
    dl = "".join(f"<dt>{_esc(k)}</dt><dd>{_esc(v)}</dd>" for k, v in rows if v)
    if dl:
        prop_parts.append(f"<dl class='kv'>{dl}</dl>")
    dos = [d for d in (img.get("dos") or []) if str(d or "").strip()]
    donts = [d for d in (img.get("donts") or []) if str(d or "").strip()]
    if dos:
        prop_parts.append("<h4>Do</h4><ul>" + "".join(f"<li>{_esc(d)}</li>" for d in dos) + "</ul>")
    if donts:
        prop_parts.append("<h4>Don't</h4><ul>" + "".join(f"<li>{_esc(d)}</li>" for d in donts) + "</ul>")
    if synth.get("iconography"):
        prop_parts.append(f"<h4>Iconography</h4><p>{_esc(synth['iconography'])}</p>")
    proposed = "".join(prop_parts) or _muted("No imagery direction synthesized (synthesis was unavailable).")

    return _dual_section("Imagery & Iconography", documented, proposed)


# ---------------------------------------------------------------------------
# Section 10 — Brand in action (cheat sheet)
# ---------------------------------------------------------------------------
def _section_cheatsheet(guide: dict, ctx: dict) -> str:
    census = guide.get("visual_census") or {}
    synth = guide.get("synthesized") or {}
    colors = [c for c in (census.get("colors") or []) if isinstance(c, dict)]
    fonts = [f for f in (census.get("fonts") or []) if isinstance(f, dict)]
    rows: list[str] = []
    if synth.get("tagline"):
        rows.append(f"<dt>Tagline</dt><dd>{_esc(synth['tagline'])}</dd>")
    if colors:
        rows.append(
            "<dt>Primary colour</dt><dd>"
            + _swatch_chip(colors[0].get("hex")) + f" <span class='mono'>{_esc(colors[0].get('hex'))}</span></dd>"
        )
    if fonts and fonts[0].get("name"):
        rows.append(f"<dt>Primary typeface</dt><dd>{_esc(fonts[0]['name'])}</dd>")
    rows.append("<dt>Brand questions</dt><dd>Route brand/usage questions to the account lead before publishing.</dd>")
    version = guide.get("version")
    generated = _fmt_date(guide.get("generated_at") or guide.get("created_at"))
    rows.append(f"<dt>Version</dt><dd>v{_esc(version)}{(' · ' + _esc(generated)) if generated else ''}</dd>")
    return (
        '<section class="sec"><h2>Brand in action</h2>'
        f"<dl class='kv cheat'>{''.join(rows)}</dl></section>"
    )


# ---------------------------------------------------------------------------
# Methodology note
# ---------------------------------------------------------------------------
def _section_methodology(guide: dict) -> str:
    census = guide.get("visual_census") or {}
    vibe = guide.get("vibe_read") or {}
    captured = guide.get("captured") or {}
    notes: list[str] = []
    palette_source = census.get("palette_source")
    if palette_source and palette_source != "none":
        notes.append(f"Palette measured from the homepage ({_esc(palette_source)} signal).")
    pc = captured.get("page_count")
    if pc:
        notes.append(f"{_esc(pc)} page(s) captured; palette/fonts/type from the homepage only.")
    if vibe.get("methodology_note"):
        notes.append(_esc(vibe["methodology_note"]))
    census_notes = [n for n in (census.get("notes") or []) if str(n or "").strip()]
    for n in census_notes[:3]:
        notes.append(_esc(n))
    if not notes:
        return ""
    return (
        '<section class="sec method"><h2>How this was made</h2>'
        + "".join(f"<p class='dim'>{n}</p>" for n in notes)
        + "</section>"
    )


# ---------------------------------------------------------------------------
# Dual-layer section wrapper
# ---------------------------------------------------------------------------
def _dual_section(title: str, documented: str, proposed: str, *, proposed_label: str = "Proposed") -> str:
    return (
        f'<section class="sec"><h2>{_esc(title)}</h2>'
        f'<div class="dual"><div class="col documented"><div class="lbl">Documented</div>{documented}</div>'
        f'<div class="col proposed"><div class="lbl">{_esc(proposed_label)}</div>{proposed}</div></div>'
        "</section>"
    )


# ---------------------------------------------------------------------------
# Full document
# ---------------------------------------------------------------------------
def build_guide_html(
    guide: dict,
    ctx: dict,
    *,
    profile: str = "client",
    agency: str = "Amazing Rankings",
    screenshot_data_uri: Optional[str] = None,
    logo_src: Optional[str] = None,
) -> str:
    """Assemble the full brand-guide HTML document (pure — WeasyPrint renders it).

    `profile` ∈ {'internal','client'}; the only delta is the aesthetic/coherence
    treatment (§4.7). `screenshot_data_uri` (the homepage capture) + `logo_src`
    are pre-inlined data URIs (or a fallback URL) supplied by the orchestrator so
    this stays pure/testable."""
    client_facing = profile != "internal"

    hero = (
        f'<section class="sec hero"><h2>The homepage today</h2>'
        f'<img class="shot" src="{_esc(screenshot_data_uri)}"/>'
        f'<p class="dim">The live homepage this guide was read from.</p></section>'
        if screenshot_data_uri else ""
    )

    sections = "".join([
        _section_foundation(guide, ctx),
        _section_audience(ctx),
        _section_voice(guide, ctx),
        hero,
        _section_aesthetic(guide, client_facing=client_facing),
        _section_color(guide),
        _section_typography(guide),
        _section_logo(guide, logo_src=logo_src),
        _section_imagery(guide),
        _section_cheatsheet(guide, ctx),
        _section_methodology(guide),
    ])

    title = _esc((ctx.get("name") or "Brand") + " — Brand Guide")
    return (
        '<!doctype html><html><head><meta charset="utf-8"/>'
        f"<title>{title}</title><style>{_CSS}</style></head><body>"
        + _cover(guide, ctx, logo_src=logo_src, agency=agency, client_facing=client_facing)
        + f"<main>{sections}</main>"
        + f'<footer>Prepared by {_esc(agency)}'
        + (" · Internal audit — not for client distribution" if not client_facing else "")
        + "</footer></body></html>"
    )


_CSS = """
@page { size: A4; margin: 16mm 15mm; @bottom-center { content: counter(page); color:#94a3b8; font-size:9px; } }
* { box-sizing: border-box; }
body { font-family: -apple-system, Helvetica, Arial, sans-serif; color:#0f172a; font-size:11px; line-height:1.5; }
.cover { text-align:center; padding:48px 0 28px; border-bottom:3px solid #6366f1; margin-bottom:26px; }
.cover .logo { max-height:72px; margin-bottom:18px; }
.cover h1 { font-size:30px; margin:0; letter-spacing:-.01em; }
.cover .subtitle { color:#6366f1; font-weight:600; letter-spacing:.06em; text-transform:uppercase; font-size:11px; margin-top:8px; }
.cover .tagline { font-size:15px; color:#334155; font-style:italic; margin-top:12px; }
.cover .meta { color:#94a3b8; font-size:10px; margin-top:14px; }
.sec { margin-bottom:22px; page-break-inside:avoid; }
h2 { font-size:15px; border-bottom:1px solid #e2e8f0; padding-bottom:6px; color:#0f172a; margin-bottom:10px; }
h4 { font-size:10px; text-transform:uppercase; letter-spacing:.04em; color:#64748b; margin:12px 0 4px; }
p { margin:5px 0; }
.na { color:#94a3b8; font-style:italic; }
.dim { color:#64748b; }
.mono { font-family:'SF Mono', ui-monospace, Menlo, Consolas, monospace; font-size:10px; }
.dual { display:flex; gap:18px; }
.dual .col { flex:1; }
.col.proposed { border-left:1px solid #eef2f6; padding-left:16px; }
.lbl { font-size:8.5px; font-weight:700; text-transform:uppercase; letter-spacing:.08em; color:#94a3b8; margin-bottom:6px; }
.col.proposed .lbl { color:#6366f1; }
ul { margin:4px 0; padding-left:16px; } li { margin-bottom:3px; }
dl.kv { margin:4px 0; } dl.kv dt { font-weight:600; color:#334155; margin-top:6px; } dl.kv dd { margin:0 0 2px; }
.chips { display:flex; flex-wrap:wrap; gap:5px; margin:4px 0; }
.chip { font-size:9px; padding:2px 8px; border-radius:10px; background:#f1f5f9; color:#334155; }
.chip.ok { background:#dcfce7; color:#166534; } .chip.no { background:#fef2f2; color:#b91c1c; }
table { width:100%; border-collapse:collapse; margin-top:6px; }
th, td { text-align:left; padding:5px 7px; border-bottom:1px solid #eef2f6; vertical-align:middle; }
th { font-size:8.5px; text-transform:uppercase; letter-spacing:.04em; color:#94a3b8; }
td.num, th.num { text-align:right; }
.trunc { max-width:220px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:9px; }
.sw { display:inline-block; width:16px; height:16px; border-radius:3px; border:1px solid rgba(0,0,0,.08); vertical-align:middle; margin-right:4px; }
.pswatches { display:flex; flex-wrap:wrap; gap:10px; margin-top:6px; }
.pswatch { width:88px; text-align:center; }
.pswatch .sw { width:100%; height:40px; display:block; margin:0 0 4px; }
.psn { font-size:10px; font-weight:600; } .psr { font-size:8.5px; color:#6366f1; text-transform:uppercase; letter-spacing:.03em; } .psh { color:#64748b; }
ul.usage { list-style:none; padding:0; } ul.usage li { margin-bottom:4px; }
.aesthetic li strong, .fonts li strong { color:#0f172a; }
.axes { margin-top:4px; }
.axis { display:flex; align-items:center; gap:8px; margin:3px 0; font-size:9px; color:#64748b; }
.axl { width:74px; text-align:right; } .axr { width:74px; }
.axtrack { flex:1; position:relative; height:5px; background:#eef2f6; border-radius:3px; }
.axdot { position:absolute; top:-2px; width:9px; height:9px; border-radius:50%; background:#6366f1; transform:translateX(-50%); }
.flags li { margin-bottom:4px; } .flag-gap strong { color:#b45309; } .flag-info strong { color:#334155; }
.hero .shot { width:100%; max-height:420px; object-fit:contain; border:1px solid #e2e8f0; border-radius:8px; }
.logo-frame { border:1px solid #e2e8f0; border-radius:8px; padding:16px; text-align:center; background:#f8fafc; margin-bottom:8px; }
.logo-frame img { max-height:80px; max-width:100%; }
.tag { font-size:8px; background:#eef2ff; color:#4f46e5; padding:1px 6px; border-radius:8px; }
.wswd td:last-child, .pair td:last-child { color:#334155; }
.cheat dt { width:120px; }
footer { margin-top:26px; padding-top:8px; border-top:1px solid #e2e8f0; color:#94a3b8; font-size:9px; text-align:center; }
.method p { font-size:9.5px; }
.tagline-line { font-size:13px; font-style:italic; color:#334155; }
"""


# ---------------------------------------------------------------------------
# Inlining (best-effort — screenshots from the bucket, logo from the web)
# ---------------------------------------------------------------------------
def _homepage_screenshot_data_uri(captured: Any) -> Optional[str]:
    """Read the stored homepage screenshot back from the `brand-guides` bucket and
    base64-inline it as a data URI (portable PDF). None on any miss/failure."""
    from services.brand_guide_vibe import homepage_screenshot_path

    path = homepage_screenshot_path(captured)
    if not path:
        return None
    try:
        png = get_supabase().storage.from_(_BRAND_GUIDE_BUCKET).download(path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("brand_guide_render.screenshot_download_failed", extra={"path": path, "error": str(exc)})
        return None
    if not png:
        return None
    return "data:image/png;base64," + base64.b64encode(png).decode()


async def _inline_logo(url: Optional[str]) -> Optional[str]:
    """Best-effort base64 data URI for a logo URL (portable PDF). Falls back to the
    raw URL (WeasyPrint fetches it at render in prod) and finally None. A data:
    URL passes straight through."""
    if not url:
        return None
    if url.startswith("data:"):
        return url
    try:
        import httpx

        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as http:
            resp = await http.get(url)
            resp.raise_for_status()
            ct = (resp.headers.get("content-type") or "").split(";")[0].strip()
            if ct.startswith("image/") and resp.content:
                return f"data:{ct};base64," + base64.b64encode(resp.content).decode()
    except Exception as exc:  # noqa: BLE001
        logger.info("brand_guide_render.logo_inline_failed", extra={"url": url[:120], "error": str(exc)[:150]})
    return url  # let WeasyPrint try the raw URL; degrades to a missing image, never fails


# ---------------------------------------------------------------------------
# Render + store + deliver (I/O — best-effort throughout)
# ---------------------------------------------------------------------------
def _render_pdf(html: str) -> bytes:
    from services.client_report import render_pdf  # WeasyPrint, lazy-imported there

    return render_pdf(html)


def _store_profile_pdf(client_id: str, guide_id: str, profile: str, pdf: bytes) -> tuple[str, Optional[str]]:
    from services.client_report import _REPORTS_BUCKET, _signed_url

    supabase = get_supabase()
    path = f"{client_id}/brand-guide/{guide_id}-{profile}.pdf"
    supabase.storage.from_(_REPORTS_BUCKET).upload(
        path, pdf, {"content-type": "application/pdf", "upsert": "true"}
    )
    return path, _signed_url(path)


async def _deliver_client_pdf(client: dict, ctx: dict, pdf: bytes) -> dict:
    """Deliver the CLIENT-profile PDF to the client's Drive folder (best-effort)."""
    from services.google_docs import resolve_drive_folder, upload_pdf

    out = {"drive": "skipped"}
    folder_id = resolve_drive_folder(client, "brand_guide")
    if not folder_id:
        return out
    title = f"{ctx.get('name') or 'Client'} — Brand Guide"
    try:
        drive = await upload_pdf(folder_id, title, pdf)
        out["drive"] = "ok"
        out["drive_doc_id"] = drive.get("file_id")
    except Exception as exc:  # incl. GoogleDocError
        out["drive"] = "failed"
        out["drive_error"] = str(exc)[:200]
        logger.warning("brand_guide_render.drive_failed", extra={"client_name": ctx.get("name"), "error": str(exc)})
    return out


async def render_and_store_guide(guide_id: str, *, deliver: bool = True) -> dict:
    """Render BOTH profiles of a stored guide → the `reports` bucket, deliver the
    client profile to Drive, and write the per-profile `renders` map + status.

    The single render entry point, called inline from the generate job (non-regulated)
    AND from the `brand_guide_render` job (regulated approve). Best-effort: a render
    failure sets `status='error'` + an honest note (the census/vibe/synthesized data
    already persisted survives), never raises. Returns a small summary."""
    import asyncio

    supabase = get_supabase()
    rows = supabase.table("brand_guides").select("*").eq("id", guide_id).limit(1).execute().data or []
    if not rows:
        return {"guide_id": guide_id, "status": "error", "error": "guide_not_found"}
    guide = rows[0]
    client_id = guide["client_id"]

    supabase.table("brand_guides").update({"status": "rendering"}).eq("id", guide_id).execute()

    client = _get_client(client_id)
    ctx = gather_render_context(client)
    agency = settings.client_report_agency_name or "Amazing Rankings"

    try:
        screenshot_uri = _homepage_screenshot_data_uri(guide.get("captured"))
        logo_src = await _inline_logo(ctx.get("logo_url"))

        renders: dict[str, dict] = {}
        client_pdf: Optional[bytes] = None
        now = datetime.now(timezone.utc).isoformat()
        for profile in PROFILES:
            html = build_guide_html(
                guide, ctx, profile=profile, agency=agency,
                screenshot_data_uri=screenshot_uri, logo_src=logo_src,
            )
            pdf = await asyncio.to_thread(_render_pdf, html)
            path, url = await asyncio.to_thread(_store_profile_pdf, client_id, guide_id, profile, pdf)
            renders[profile] = {"storage_path": path, "pdf_url": url, "rendered_at": now}
            if profile == "client":
                client_pdf = pdf

        # Deliver the client-facing profile to Drive (best-effort).
        if deliver and client_pdf is not None:
            delivery = await _deliver_client_pdf(client, ctx, client_pdf)
            renders.setdefault("client", {})["delivery"] = delivery

        # Mirror the client profile into the top-level columns (the deliverable).
        client_render = renders.get("client") or {}
        supabase.table("brand_guides").update({
            "status": "done",
            "renders": renders,
            "storage_path": client_render.get("storage_path"),
            "pdf_url": client_render.get("pdf_url"),
            "generated_at": "now()",
            "error": None,
        }).eq("id", guide_id).execute()
        logger.info("brand_guide_render.done",
                    extra={"guide_id": guide_id, "client_id": client_id,
                           "profiles": list(renders.keys())})
        return {
            "guide_id": guide_id, "status": "done",
            "profiles": list(renders.keys()),
            "pdf_url": client_render.get("pdf_url"),
            "delivery": (renders.get("client") or {}).get("delivery"),
        }
    except Exception as exc:  # noqa: BLE001
        note = f"render error: {type(exc).__name__}: {str(exc)[:300]}"
        logger.warning("brand_guide_render.failed", extra={"guide_id": guide_id, "error": note})
        supabase.table("brand_guides").update(
            {"status": "error", "error": note}
        ).eq("id", guide_id).execute()
        return {"guide_id": guide_id, "status": "error", "error": note}


def _get_client(client_id: str) -> dict:
    try:
        rows = get_supabase().table("clients").select("*").eq("id", client_id).limit(1).execute().data or []
        return rows[0] if rows else {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("brand_guide_render.client_fetch_failed", extra={"client_id": client_id, "error": str(exc)})
        return {}


# ---------------------------------------------------------------------------
# The regulated sign-off render job (enqueued on an admin/staff approval)
# ---------------------------------------------------------------------------
def enqueue_brand_guide_render(client_id: str, guide_id: str, user_id: Optional[str] = None) -> str:
    """Enqueue the separate `brand_guide_render` job for a regulated guide that a
    human has approved out of `awaiting_signoff` (PRD §5.3b / §6). Returns the job
    id. The approval ENDPOINT/UI is Phase 4; this is the job it enqueues."""
    row = get_supabase().table("async_jobs").insert({
        "job_type": "brand_guide_render", "entity_id": client_id,
        "payload": {"guide_id": guide_id, "client_id": client_id, "user_id": user_id},
    }).execute().data[0]
    return row["id"]


async def run_brand_guide_render_job(job: dict) -> None:
    """async_jobs handler for job_type='brand_guide_render' (PRD §6).

    Gated on `brand_guide_enabled`. Renders + stores + delivers a guide that a human
    approved out of `awaiting_signoff` (the render/approval seam is Phase 3 here; the
    approve endpoint/UI lands in Phase 4)."""
    job_id = job["id"]
    payload = job.get("payload") or {}
    supabase = get_supabase()

    if not settings.brand_guide_enabled:
        supabase.table("async_jobs").update(
            {"status": "complete",
             "result": {"skipped": "brand_guide_disabled"},
             "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return

    guide_id = payload.get("guide_id")
    if not guide_id:
        supabase.table("async_jobs").update(
            {"status": "failed", "error": "missing guide_id", "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return

    logger.info("brand_guide_render.started", extra={"job_id": job_id, "guide_id": guide_id})
    try:
        result = await render_and_store_guide(guide_id, deliver=True)
    except Exception as exc:  # noqa: BLE001 — render_and_store is best-effort, but belt-and-braces
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return

    supabase.table("async_jobs").update(
        {"status": "complete", "result": result, "completed_at": "now()"}
    ).eq("id", job_id).execute()
