/**
 * URL and namespace rules from the Page Type Reference v3.6 §1.2.
 *
 * These are ratified conventions, not preferences: reserved paths, root
 * precedence, trailing slashes, and breadcrumbs that follow the URL path so
 * BreadcrumbList and canonical can never disagree.
 */

/**
 * Fixed paths the system claims. A service, city, or pillar slug colliding with
 * one of these is "a planning error to surface, never to silently resolve"
 * (reference §1.2) — so the build fails rather than letting one silently win.
 *
 * The first fifteen are the reference's list. `sitemap`, `search` and `404` are
 * additions this module makes (PRD §4.8c) and are worth feeding back for
 * ratification.
 */
export const RESERVED_ROOT_SLUGS = new Set([
  'about-us',
  'services',
  'areas-we-serve',
  'blog',
  'contact-us',
  'privacy-policy',
  'faq',
  'specials',
  'warranty',
  'projects',
  'glossary',
  'bio',
  'compare',
  'lp',
  'reviews',
  // Module additions (PRD §4.8c)
  'sitemap',
  'search',
  '404',
]);

/** `cost` is reserved at the SECOND level under a service, not at root. */
export const RESERVED_SECOND_LEVEL = new Set(['cost']);

export const segmentsOf = (path: string): string[] =>
  path.split('/').filter(Boolean);

/** Every URL carries a trailing slash (reference §1.2). */
export const normalizePath = (path: string): string => {
  const segs = segmentsOf(path);
  return segs.length ? `/${segs.join('/')}/` : '/';
};

/** Archive pagination is /{archive}/page/{n}/ (reference §1.2). */
export const paginatedPath = (archive: string, page: number): string =>
  page <= 1 ? normalizePath(archive) : normalizePath(`${archive}/page/${page}`);

/**
 * Ancestor paths, nearest-parent last-but-one, excluding the page itself.
 * "/anaheim/ac-repair/" → ["/", "/anaheim/"].
 *
 * Breadcrumbs follow the URL path, not the link hierarchy — so a local landing
 * page's breadcrumb parent is its CITY page, and the Services index is not an
 * ancestor of a service page even though it links to one.
 */
export function ancestorPaths(path: string): string[] {
  const segs = segmentsOf(path);
  const out = ['/'];
  for (let i = 1; i < segs.length; i += 1) {
    out.push(`/${segs.slice(0, i).join('/')}/`);
  }
  return out;
}

export interface PathConflict {
  kind: 'reserved' | 'duplicate';
  path: string;
  detail: string;
}

/**
 * Build-time backstop for the two planning errors the reference names.
 *
 * The planner is supposed to catch both before anything is generated, but a
 * silently-wrong URL outlives the mistake that made it, so the site refuses to
 * build rather than shipping one page that quietly won a contested path.
 */
export function findPathConflicts(
  entries: { path: string; label: string }[],
): PathConflict[] {
  const conflicts: PathConflict[] = [];
  const seen = new Map<string, string>();

  for (const entry of entries) {
    const path = normalizePath(entry.path);
    const segs = segmentsOf(path);

    if (segs.length === 1 && RESERVED_ROOT_SLUGS.has(segs[0])) {
      conflicts.push({
        kind: 'reserved',
        path,
        detail: `"${entry.label}" claims reserved root slug "${segs[0]}"`,
      });
    }
    if (segs.length === 2 && RESERVED_SECOND_LEVEL.has(segs[1])) {
      conflicts.push({
        kind: 'reserved',
        path,
        detail: `"${entry.label}" claims reserved second-level slug "${segs[1]}"`,
      });
    }

    const prior = seen.get(path);
    if (prior) {
      conflicts.push({
        kind: 'duplicate',
        path,
        detail: `"${prior}" and "${entry.label}" both claim ${path}`,
      });
    } else {
      seen.set(path, entry.label);
    }
  }

  return conflicts;
}
