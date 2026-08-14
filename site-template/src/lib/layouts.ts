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
// compiler's `validate_layouts` whitelist — a value one side knows and the
// other doesn't is exactly what the default guards against.
const HERO_IMAGE_POSITIONS = new Set<HeroImagePosition>(['right', 'left', 'none']);

// Matches the current hardcoded behaviour, so an absent manifest (the house
// theme) renders exactly as before this seam existed.
const HERO_IMAGE_DEFAULT: HeroImagePosition = 'right';

interface LayoutManifest {
  version?: number;
  screens?: Record<string, { hero?: { image?: string } }>;
}

const manifest = raw as unknown as LayoutManifest;

/** The hero image position for a screen, defaulting safely. */
export function heroImagePosition(screen: string): HeroImagePosition {
  const value = manifest.screens?.[screen]?.hero?.image;
  return HERO_IMAGE_POSITIONS.has(value as HeroImagePosition)
    ? (value as HeroImagePosition)
    : HERO_IMAGE_DEFAULT;
}
