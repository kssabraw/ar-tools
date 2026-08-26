import type { RoutedPage } from './content';
import { site, isLocal } from './site';
import type { NavItem } from './site';

/**
 * The CORE-conditional hubs, and the global nav that links to them.
 *
 * Page Type Reference v3.5 (note R6) promotes **Areas We Serve** and the
 * **Services index** out of "optional / case-by-case": they are auto-triggered
 * infrastructure that fires on essentially every real multi-city or
 * multi-service site.
 *
 * Both trigger conditions live here rather than in the routes, because the
 * routes and the nav must agree exactly — a nav linking to a hub the route
 * declined to build is a 404 in the global nav of every page on the site, which
 * is the worst place to put one.
 *
 * **These thresholds mirror `services/website_plan.py`.** The planner decides
 * whether to *plan* the hub; this file decides whether to *render* it. They are
 * the same rule evaluated in two places, so a change to one needs the other.
 */

/** Reference §5.1: "> 8 top-level services" — too many for a nav dropdown. */
export const SERVICES_INDEX_TRIGGER = 8;

/**
 * Ratified at 6 by the owner (2026-08-06), settling reference note R6's open
 * threshold and superseding the ">= 2 targeted cities" in the v3.6 capture.
 *
 * Below it a site has location pages and a matrix but no location hub, and
 * nothing in the global nav points at the location silo — those cities are
 * reached from the homepage grid, from every matrix page's structural links,
 * and from the HTML sitemap. §4.1 rule 4 lists Areas We Serve as "where
 * applicable", so that is conformant.
 */
export const AREAS_WE_SERVE_TRIGGER = 6;

/** Top-level services only — sub-services live under their parent. */
export const topLevelServices = (pages: RoutedPage[]): RoutedPage[] =>
  pages.filter((p) => p.pageType === 'service');

export const cityPages = (pages: RoutedPage[]): RoutedPage[] =>
  pages.filter((p) => p.pageType === 'location');

/**
 * Whether this site gets a Services index.
 *
 * At or below the threshold the reference is explicit that it should NOT be
 * built — the services are listed directly in the nav, and building the hub
 * anyway adds a hierarchy layer that only dilutes link equity.
 */
export const hasServicesIndex = (pages: RoutedPage[]): boolean =>
  isLocal && topLevelServices(pages).length > SERVICES_INDEX_TRIGGER;

/** A single-city business has no location pages, so it has no location hub. */
export const hasAreasWeServe = (pages: RoutedPage[]): boolean =>
  isLocal && cityPages(pages).length >= AREAS_WE_SERVE_TRIGGER;

/**
 * The SOP global nav set (PRD §4.1 rule 4), derived from what is actually
 * published rather than from stored config.
 *
 * Derived by default for the same reason structural links are: it self-heals.
 * A site that gains its second city gets an Areas We Serve entry on the next
 * deploy, with no config re-commit and no chance of the nav pointing at a page
 * that was never built. An explicit `nav` in site.config.json overrides this
 * for the rare hand-curated case.
 */
export function globalNav(pages: RoutedPage[], hasPosts: boolean): NavItem[] {
  if (site.nav.length > 0) return site.nav;

  const items: NavItem[] = [];

  if (isLocal) {
    const services = topLevelServices(pages);
    if (hasServicesIndex(pages)) {
      items.push({ label: 'Services', href: '/services/' });
    } else {
      // Under the threshold the services themselves are the nav (reference
      // §5.1). Capped so a 7-service site does not produce an unusable bar.
      items.push(...services.slice(0, SERVICES_INDEX_TRIGGER).map((s) => ({ label: s.title, href: s.path })));
    }
    if (hasAreasWeServe(pages)) items.push({ label: 'Areas We Serve', href: '/areas-we-serve/' });
  } else {
    // An informational site leads with its pillar/hub guides (reference §5.3:
    // pillars are linked from nav). Capped like the service bar.
    const pillars = pages.filter((p) => p.pageType === 'pillar');
    items.push(...pillars.slice(0, SERVICES_INDEX_TRIGGER).map((p) => ({ label: p.title, href: p.path })));
  }

  if (hasPosts) items.push({ label: 'Blog', href: '/blog/' });
  items.push({ label: 'About Us', href: '/about-us/' });
  items.push({ label: 'Contact Us', href: '/contact-us/' });

  return items;
}

/**
 * The SOP global footer set. Privacy Policy is mandatory in it; the HTML
 * sitemap joins it because it is the one page that lists everything (§4.8c).
 */
export function globalFooterNav(pages: RoutedPage[], hasPosts: boolean): NavItem[] {
  if (site.footerNav.length > 0) return site.footerNav;

  const items: NavItem[] = [{ label: 'About Us', href: '/about-us/' }];
  if (isLocal && hasAreasWeServe(pages)) {
    items.push({ label: 'Areas We Serve', href: '/areas-we-serve/' });
  }
  if (hasPosts) items.push({ label: 'Blog', href: '/blog/' });
  items.push({ label: 'Contact Us', href: '/contact-us/' });
  items.push({ label: 'Privacy Policy', href: '/privacy-policy/' });
  items.push({ label: 'Sitemap', href: '/sitemap/' });
  return items;
}
