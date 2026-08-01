# ar-site-template

The house Astro template every generated website is built from — the first
slice of the **Website Builder** module
(`docs/modules/website-builder-module-plan-v1_0.md`).

This directory is the **source of truth**. It gets published to a standalone
GitHub *template repository* (`kssabraw/ar-site-template`), and the provisioner
creates each site by generating a new repo from that template
(`POST /repos/{template}/generate`). Edit it here; publish from here.

## Why it exists

Everything that is identical for every site lives here, so the theme compiler
only has to produce *the design*. That split is what lets template
improvements — dependency bumps, new SEO plumbing, a fixed bug — roll out to
every existing site repo without touching any site's look.

**The repo is the site.** A generated site has no runtime dependency on the
suite: push to `main` and GitHub Actions builds and deploys it. If the suite
disappeared tomorrow, every site keeps building and shipping.

## The theme contract

> Everything theme-specific lives in `src/theme/`. Nothing outside it is.

- `src/theme/tokens.css` — the design tokens. **A theme swap is, in the simple
  case, only this file.**
- `src/theme/base.css` — reset plus shared primitives (`.wrap`, `.card`,
  `.richtext`, `.button`). Not theme-specific.
- `src/theme/components/*.astro` — the section components, each with named
  content slots.

The compiler writes `src/theme/**` and `site.config.json`, and nothing else.

## Layout

```
site.config.json          per-site config written by the provisioner (see below)
astro.config.mjs          reads site.config.json for the canonical site URL
wrangler.jsonc            `name` is rewritten per site by the provisioner
.github/workflows/        push to main -> astro build -> wrangler deploy
src/content.config.ts     the frontmatter contract (zod-validated)
src/content/              posts | services | locations | pages
src/lib/site.ts           typed config access + the `has()` degradation helper
src/lib/schema.ts         deterministic JSON-LD, built from facts only
src/lib/content.ts        collection queries; deterministic ordering
src/layouts/Layout.astro  head, SEO, JSON-LD, sanctioned third-party snippets
src/pages/                routes
```

## Two site types, one template

`site.config.json`'s `siteType` is `informational` or `local_business`, and the
routes adapt:

| Route | Informational | Local business |
|---|---|---|
| `/` | hero + latest + topics | hero + services + reviews + areas + blog + CTA |
| `/blog/`, `/topics/` | yes | only if posts exist |
| `/services/`, `/locations/` | **never built** | yes |
| `/about`, `/contact`, `/privacy` | yes | yes |

Each section route pairs its index with its detail page in one `[...slug]`
file. That is deliberate: `getStaticPaths` returns `[]` when a collection is
empty, so a site with no services builds **no `/services/` page at all** rather
than publishing an empty listing. A separate `index.astro` could not do that.

## Degradation is the default

A brand-new business has no GBP, no reviews, no street address, and possibly no
photos. Every section checks its inputs and renders nothing rather than an empty
shell (plan §4.5): no reviews → no review strip; no address → `areaServed`
instead, and no map; no images → no image frames; no form key → no dead form.

## Two rules that are easy to break

1. **`phoneReal` vs `phoneDisplayed`.** JSON-LD and citations always get
   `phoneReal`. Visible markup and `tel:` links get `phoneDisplayed` — the
   CallRail tracking number when one is configured. Never swap these.
2. **JSON-LD is built from facts, never from prose.** `src/lib/schema.ts` reads
   `site.config.json`; generated copy never reaches it. A page therefore cannot
   claim something the business hasn't told us.

## `site.config.json`

Written by the provisioner. `business.provenance` records `"user"` or `"gbp"`
per field, so a later GBP sync fills gaps without overwriting anything a human
typed. `analytics` holds the post-launch snippets (GA4, CallRail); `forms`
holds the Web3Forms access key.

## Local development

```bash
npm install
npm run dev        # http://localhost:4321
npm run build      # -> dist/
```

To exercise the local-business path, set `siteType` to `local_business`, add
`business` facts, and drop a markdown file into `src/content/services/`.

## Sample content

`src/content/posts/sample-*.md` and `src/content/pages/about.md` ship so a fresh
clone builds into something viewable. **The provisioner clears `src/content/`
before generating a real site's content.**
