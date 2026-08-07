import raw from '../../site.config.json' with { type: 'json' };

export interface NavItem {
  label: string;
  href: string;
}

export interface BusinessFacts {
  name: string;
  legalName: string;
  /** Canonical number: goes in JSON-LD and citations. Never swapped. */
  phoneReal: string;
  /** What visitors see — a CallRail tracking number when one is configured. */
  phoneDisplayed: string;
  email: string;
  street: string;
  city: string;
  region: string;
  postalCode: string;
  country: string;
  areaServed: string[];
  categories: string[];
  hours: string[];
  mapPlaceId: string;
  rating: string;
  reviewCount: string;
  reviews: Review[];
  /** Structured, because §5.3 checks generated copy against them. A free-text
   *  "licensed and insured" field would defeat that check. */
  credentials: Credential[];
  /** Per-field `"user" | "gbp"` marks, so a later GBP sync fills gaps without
   *  clobbering anything typed by a human (plan §4.5). */
  provenance: Record<string, string>;
}

export interface Credential {
  type: string;
  issuingBody: string;
  number?: string;
  expires?: string;
}

export interface Review {
  author: string;
  rating: number;
  text: string;
}

export interface SiteConfig {
  siteName: string;
  siteType: 'informational' | 'local_business';
  url: string;
  tagline: string;
  description: string;
  locale: string;
  nav: NavItem[];
  footerNav: NavItem[];
  business: BusinessFacts;
  forms: { web3formsKey: string };
  analytics: { ga4: string; callrailSnippet: string };
  agency: { name: string };
}

const parsed = raw as unknown as SiteConfig;

// Guarantee the array-typed business facts actually ARE arrays at runtime. The
// config is cast, not validated, and a generated config only carries the keys a
// business had — so a site with no hours or no service-area list omits them
// entirely, and a component reading `business.hours.length` would crash the
// build. The BusinessFacts type says these are string[]; this makes that true.
if (parsed.business) {
  parsed.business.hours = Array.isArray(parsed.business.hours) ? parsed.business.hours : [];
  parsed.business.areaServed = Array.isArray(parsed.business.areaServed) ? parsed.business.areaServed : [];
}

export const site = parsed;

export const isLocal = site.siteType === 'local_business';

/** True when a fact exists — every section hides itself rather than rendering
 *  an empty shell, which is what makes the no-GBP path (§4.5) work. */
export const has = (v: unknown): boolean =>
  Array.isArray(v) ? v.length > 0 : typeof v === 'string' ? v.trim() !== '' : Boolean(v);

/** The number to show. Falls back to the real one when no tracking number is set. */
export const displayPhone = (): string =>
  site.business.phoneDisplayed || site.business.phoneReal;

export const hasAddress = (): boolean =>
  has(site.business.street) && has(site.business.city);

/** Service-area businesses and pre-launch clients often have no street address;
 *  those sites still get a valid postal locality block from city/region. */
export const formattedAddress = (): string => {
  const b = site.business;
  return [b.street, b.city, [b.region, b.postalCode].filter(has).join(' ')]
    .filter(has)
    .join(', ');
};

export const canonical = (path: string, base: string | URL = site.url): string =>
  new URL(path, base).toString();
