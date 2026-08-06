/**
 * What this theme provides, in Shared Component Library vocabulary
 * (Page Type Reference v3.6 §4).
 *
 * PRD §4.5: "A theme missing a component a planned page type needs is reported
 * at THEME APPROVAL, not discovered at publish." That check needs the theme to
 * declare itself — this is that declaration. A compiled theme must ship its own
 * manifest; the coverage check reads this file, not the filesystem, so a
 * component that exists but is not wired counts as absent.
 */
export const PROVIDED_COMPONENTS = [
  'HeroStandard',
  'HeroAnswer',
  'CTABand',
  'FAQAccordion',
  'TestimonialCard',
  'ServiceCardGrid',
  'LocationCardGrid',
  'MapEmbed',
  'TrustBadgeRow',
  'AuthorByline',
  'LeadForm',
  'RelatedPagesBlock',
  'BreadcrumbBar',
  'AlertNote',
] as const;

/**
 * Library components this theme does NOT provide. Listed explicitly rather than
 * left implicit, because each one gates a page type: planning a Cost page
 * against this theme should fail at approval with a name, not render through
 * the wrong template.
 *
 * Most map to page types that have no writer yet (PRD §4.7), so building them
 * now would be speculative.
 */
export const MISSING_COMPONENTS = [
  'ComparisonTable',
  'PriceRangeTable',
  'PricingTierCards',
  'StatCallout',
  'StepList',
  'ProsConsPair',
  'ProofBlock',
  'LogoRow',
  'TOCSidebar',
  'GalleryBeforeAfter',
  'SpecTable',
  'CalculatorShell',
  'DefinitionBox',
] as const;

export type ProvidedComponent = (typeof PROVIDED_COMPONENTS)[number];
