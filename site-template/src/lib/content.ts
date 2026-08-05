import { getCollection, type CollectionEntry } from 'astro:content';
import { isLocal } from './site';
import { ancestorPaths, findPathConflicts, normalizePath } from './routes';

/**
 * Collection helpers shared by the routes.
 *
 * Every list filters drafts and sorts deterministically, so two builds of the
 * same content produce byte-identical output — which keeps deploy diffs
 * meaningful and makes "did anything actually change?" answerable.
 *
 * These queries return PUBLISHED entries only, which is what makes structural
 * internal linking self-healing: a page held by a quality gate is simply absent
 * from its neighbours' link lists rather than linked and broken, and it gains
 * its inbound links on the next deploy once it publishes. No build-time link
 * resolver is needed (PRD §4.8b).
 */

const live = <T extends { data: { draft: boolean } }>(entries: T[]): T[] =>
  entries.filter((e) => !e.data.draft);

const byDate = (a: CollectionEntry<'posts'>, b: CollectionEntry<'posts'>): number => {
  const at = a.data.publishDate?.getTime() ?? 0;
  const bt = b.data.publishDate?.getTime() ?? 0;
  if (at !== bt) return bt - at;
  return a.id.localeCompare(b.id);
};

const byOrder = (a: { data: { order: number }; id: string }, b: { data: { order: number }; id: string }) =>
  a.data.order - b.data.order || a.id.localeCompare(b.id);

export async function allPosts(): Promise<CollectionEntry<'posts'>[]> {
  return live(await getCollection('posts')).sort(byDate);
}

/** Services, sub-services and brand × service pages. Local-only concept. */
export async function allServices(): Promise<CollectionEntry<'services'>[]> {
  if (!isLocal) return [];
  return live(await getCollection('services')).sort(byOrder);
}

/** City and neighborhood pages. */
export async function allLocations(): Promise<CollectionEntry<'locations'>[]> {
  if (!isLocal) return [];
  return live(await getCollection('locations')).sort(byOrder);
}

/** The service × city matrix. */
export async function allLocalLandings(): Promise<CollectionEntry<'localLanding'>[]> {
  if (!isLocal) return [];
  return live(await getCollection('localLanding')).sort((a, b) => a.id.localeCompare(b.id));
}

/** One page in the root namespace, flattened across the three collections. */
export interface RoutedPage {
  path: string;
  pageType: string;
  title: string;
  description: string;
  teaser: string;
  entry:
    | CollectionEntry<'services'>
    | CollectionEntry<'locations'>
    | CollectionEntry<'localLanding'>;
}

/**
 * Every routed page, deduped and validated.
 *
 * Throws on a reserved-slug collision or two entries claiming one path. The
 * planner should have caught both, but a wrong URL outlives the mistake that
 * produced it, so the build refuses rather than letting one page silently win a
 * contested path (reference §1.2; PRD acceptance criterion D).
 */
export async function routedPages(): Promise<RoutedPage[]> {
  const [services, locations, landings] = await Promise.all([
    allServices(),
    allLocations(),
    allLocalLandings(),
  ]);

  const pages: RoutedPage[] = [
    ...services.map((entry) => ({
      path: normalizePath(entry.data.path),
      pageType: entry.data.pageType,
      title: entry.data.title,
      description: entry.data.description,
      teaser: entry.data.teaser,
      entry,
    })),
    ...locations.map((entry) => ({
      path: normalizePath(entry.data.path),
      pageType: entry.data.pageType,
      title: entry.data.title,
      description: entry.data.description,
      teaser: entry.data.teaser,
      entry,
    })),
    ...landings.map((entry) => ({
      path: normalizePath(entry.data.path),
      pageType: entry.data.pageType,
      title: entry.data.title,
      description: entry.data.description,
      teaser: entry.data.teaser,
      entry,
    })),
  ];

  const conflicts = findPathConflicts(pages.map((p) => ({ path: p.path, label: p.title })));
  if (conflicts.length > 0) {
    const detail = conflicts.map((c) => `  · [${c.kind}] ${c.detail}`).join('\n');
    throw new Error(`URL namespace conflicts — the site cannot build:\n${detail}`);
  }

  return pages.sort((a, b) => a.path.localeCompare(b.path));
}

export interface Crumb {
  label: string;
  href: string;
}

/**
 * Breadcrumb trail derived from the URL path (reference §1.2), so
 * BreadcrumbList and canonical never disagree.
 *
 * An ancestor with no published page of its own is skipped rather than linked —
 * a crumb pointing at a 404 is worse than a shorter trail.
 */
export function breadcrumbsFor(path: string, pages: RoutedPage[], title: string): Crumb[] {
  const byPath = new Map(pages.map((p) => [p.path, p]));
  const crumbs: Crumb[] = [{ label: 'Home', href: '/' }];

  for (const ancestor of ancestorPaths(path).slice(1)) {
    const page = byPath.get(ancestor);
    if (page) crumbs.push({ label: page.title, href: ancestor });
  }

  crumbs.push({ label: title, href: normalizePath(path) });
  return crumbs;
}

/** Optional core page — absent is normal, so callers fall back to config. */
export async function corePage(id: string): Promise<CollectionEntry<'pages'> | undefined> {
  // Filtered from the whole collection rather than fetched by id: getEntry logs
  // a "not found" warning on every miss, which would mean a wall of noise in
  // the deploy log for pages that were never meant to exist.
  const pages = await getCollection('pages');
  return pages.find((p) => p.id === id && !p.data.draft);
}

export function categoriesOf(posts: CollectionEntry<'posts'>[]): string[] {
  return [...new Set(posts.map((p) => p.data.category).filter(Boolean))].sort();
}

export const slugify = (value: string): string =>
  value
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '');

/** Same category first, then newest, so the rail is never empty on a thin site. */
export function relatedTo(
  post: CollectionEntry<'posts'>,
  posts: CollectionEntry<'posts'>[],
  limit = 3,
): CollectionEntry<'posts'>[] {
  const others = posts.filter((p) => p.id !== post.id);
  const same = others.filter((p) => p.data.category === post.data.category);
  return [...same, ...others.filter((p) => !same.includes(p))].slice(0, limit);
}

/**
 * Structural internal links for a routed page (PRD §4.8b). Deterministic, from
 * frontmatter — no model is involved and no generation call is made, so a link
 * derived from citySlug + serviceSlug cannot point at a page that was never
 * planned.
 */
export function structuralLinks(page: RoutedPage, pages: RoutedPage[]): {
  siblingServices: RoutedPage[];
  sameServiceNearby: RoutedPage[];
  children: RoutedPage[];
} {
  const segs = page.path.split('/').filter(Boolean);
  const children = pages.filter(
    (p) => p.path.startsWith(page.path) && p.path !== page.path &&
      p.path.split('/').filter(Boolean).length === segs.length + 1,
  );

  if (page.pageType !== 'local_landing') {
    return { siblingServices: [], sameServiceNearby: [], children };
  }

  const [citySlug, serviceSlug] = segs;
  return {
    // Other services in this city.
    siblingServices: pages.filter(
      (p) => p.pageType === 'local_landing' && p.path.startsWith(`/${citySlug}/`) && p.path !== page.path,
    ),
    // The same service in other cities.
    sameServiceNearby: pages.filter(
      (p) =>
        p.pageType === 'local_landing' &&
        p.path.endsWith(`/${serviceSlug}/`) &&
        !p.path.startsWith(`/${citySlug}/`),
    ),
    children,
  };
}
