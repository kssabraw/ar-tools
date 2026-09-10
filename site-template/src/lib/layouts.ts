import raw from '../theme/layouts.json' with { type: 'json' };

/**
 * Per-screen layout selection — which *variant* of a robust house component a
 * screen renders. This is the seam that lets a compiled theme carry a design's
 * layout intent (image-left vs image-right hero, …) without generating bespoke
 * markup: the compiler writes `layouts.json`, the hand-written page templates
 * read it through this resolver, and every value is validated against a fixed
 * whitelist here.
 *
 * Why a resolver and not a direct import: the manifest is *generated* data, so
 * it is treated as untrusted. An unknown screen, a missing field, or a variant
 * this template version doesn't implement all resolve to the safe default —
 * a compiled theme can never select a layout that breaks the build, the same
 * guarantee `validate_roles` gives tokens.css.
 */

/** Where the hero image sits relative to the copy. `none` is a text-only hero. */
export type HeroImagePosition = 'right' | 'left' | 'none';

// The set this template version can actually render. Kept in lockstep with the
// compiler's HERO_IMAGE_POSITIONS whitelist (a cross-language test asserts it) —
// a value one side knows and the other doesn't is what the default guards against.
const HERO_IMAGE_POSITIONS = new Set<HeroImagePosition>(['right', 'left', 'none']);

// Matches the current hardcoded behaviour, so an absent manifest (the house
// theme) renders exactly as before this seam existed.
const HERO_IMAGE_DEFAULT: HeroImagePosition = 'right';

/**
 * Which *hero layout* a screen renders — the second layout lever (image side is
 * the first). Orthogonal to position:
 *
 *  - `band`  — a full-width image band below a PageHeader. The house default for
 *    every inner page (service / location / pillar / post).
 *  - `split` — image beside the copy (HeroStandard), the side chosen by
 *    `heroImagePosition`. The house default for the home hero.
 *  - `background` — a full-bleed hero: the image behind overlaid copy
 *    (HeroBackground).
 *
 * The DEFAULT is caller-supplied rather than fixed here, because it differs by
 * page: the home hero is `split` today, every inner page is `band`. So an absent
 * manifest (the house theme) resolves to each caller's current behaviour — the
 * same byte-identical guarantee `heroImagePosition`'s default gives.
 */
export type HeroLayout = 'band' | 'split' | 'background';

// In lockstep with the compiler's HERO_LAYOUTS whitelist (cross-language test).
const HERO_LAYOUTS = new Set<HeroLayout>(['band', 'split', 'background']);

/** How many columns the card grids use. A theme-wide trait, not per-screen. */
export type CardColumns = 2 | 3 | 4;

const CARD_COLUMNS = new Set<CardColumns>([2, 3, 4]);

interface LayoutManifest {
  version?: number;
  screens?: Record<string, { hero?: { image?: string; layout?: string } }>;
  components?: { cardColumns?: number };
}

const manifest = raw as unknown as LayoutManifest;

/** The hero image position for a screen, defaulting safely. */
export function heroImagePosition(screen: string): HeroImagePosition {
  const value = manifest.screens?.[screen]?.hero?.image;
  return HERO_IMAGE_POSITIONS.has(value as HeroImagePosition)
    ? (value as HeroImagePosition)
    : HERO_IMAGE_DEFAULT;
}

/**
 * The hero layout a screen renders, or the caller's `fallback` when the design
 * didn't declare one (or declared one this template version can't render). The
 * fallback is how each page keeps its current default — pass `'split'` for the
 * home hero, `'band'` for an inner page.
 */
export function heroLayout(screen: string, fallback: HeroLayout): HeroLayout {
  const value = manifest.screens?.[screen]?.hero?.layout;
  return HERO_LAYOUTS.has(value as HeroLayout) ? (value as HeroLayout) : fallback;
}

/**
 * The manifest screen key an inner page's hero reads. A design names its screens
 * by page family (home / service / location / …), while a routed page carries a
 * finer `pageType`; this folds the family together so a sub-service reads the
 * `service` screen's hero layout, a neighborhood the `location` screen's, and so
 * on. A page family the design never drew simply misses the manifest and falls
 * back to the caller's default — safe, never a broken layout.
 */
export function heroScreenKey(pageType: string): string {
  switch (pageType) {
    case 'service':
    case 'sub_service':
    case 'brand_service':
    case 'cost':
      return 'service';
    case 'location':
    case 'neighborhood':
    case 'local_landing':
    case 'hyper_local':
      return 'location';
    case 'pillar':
      return 'pillar';
    case 'post':
    case 'problem':
      return 'blog_post';
    default:
      return pageType;
  }
}

/**
 * The card-grid column count the theme selects, or `undefined` when the design
 * didn't declare one — in which case each grid keeps its own content-tuned
 * density (the house behaviour). Validated against the fixed set so a compiled
 * theme can never ask for a column count the grid can't render.
 */
export function cardColumns(): CardColumns | undefined {
  const value = manifest.components?.cardColumns;
  return CARD_COLUMNS.has(value as CardColumns) ? (value as CardColumns) : undefined;
}
