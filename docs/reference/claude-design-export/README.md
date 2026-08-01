# Claude Design export — reference sample

**What this is.** A real, unmodified Claude Design export, kept as the **format authority and Phase 1 test fixture** for the Website Builder module (`docs/modules/website-builder-module-plan-v1_0.md` §4.3). Received from the owner 2026-08-01. Do not edit these files — they are a captured sample, not source.

Original archive: `Informational_site_design.zip` (an informational/blog site design).

| File | What it is | Role in the compiler |
|---|---|---|
| `healthnotes.dc.html` | **The design.** A six-screen informational site (home / topics / article / about / privacy / contact) in one file. | The thing the theme compiler ingests. |
| `Health Site Directions.dc.html` | **A canvas/directions doc** — carries `<meta name="design_doc_mode" content="canvas">` and holds the exploration turns (several design *options* per turn, in `dv-turn`/`dv-opt` cards). | The thing the ingest step must **detect and exclude**. An export can contain both. |
| `support.js` | The generated `dc-runtime` — the client-side React renderer for the DSL. Header says *"GENERATED from dc-runtime/src/\*.ts — do not edit."* | Not shipped by us (we compile away from it), but it is the **semantic authority** for what `sc-if` / `sc-for` / `{{ }}` / `style-hover` actually do. Consult it when the pre-pass needs exact behavior. |

Not committed: the archive's `.thumbnail` (a WebP preview image; the real pipeline reuses it as the theme-library card image).

## Format at a glance

`.dc.html` is not plain HTML — it is a prototype in a small custom DSL, rendered client-side:

- `<x-dc>` wraps the template; `<helmet data-dc-atomics>` carries head content (Google Fonts links + a global `<style>`).
- `<script type="text/x-dc" data-dc-script>` holds a `class Component extends DCLogic` with `state` and `renderVals()` — the latter returns every binding the template uses, **including sample data arrays**.
- `<sc-if value="{{ isHome }}">` switches screens; `<sc-for list="{{ latest }}" as="a">` repeats items; `{{ … }}` interpolates; `onClick="{{ goHome }}"` binds handlers; `style-hover="…"` adds hover styling; `hint-placeholder-val` / `hint-placeholder-count` are design-time preview hints.

## Why these four things matter (see §4.3 for the full treatment)

1. **One file = the whole site.** Six `sc-if` branches → six Astro templates. One export yields the complete page-type set.
2. **`sc-for` + the sample arrays are a schema contract.** `latest` / `catList` / `related` carry `{cat, title, read, photo}` — the frontmatter the design expects. Read the shape, discard the rows.
3. **Styling is 100% inline `style="…"`** — no classes, no stylesheet. Token extraction is a frequency census over literals (accent `oklch(0.5 0.1 180)` appears 21×).
4. **Zero images.** No `<img>` anywhere; placeholders are labelled strings (`[ hero photo: plated balanced meal ]`). Confirms the §4.7 imagery ladder is load-bearing — and those labels are reusable as image-generation prompt seeds.

Also note the prototype's navigation machinery (`state.screen`, `go*()` handlers, `isX` flags) exists only because a prototype cannot route. Astro has real routes, so the compiler **discards it** and emits `<a href>`.
