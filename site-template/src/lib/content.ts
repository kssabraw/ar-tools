import { getCollection, type CollectionEntry } from 'astro:content';
import { isLocal } from './site';

/**
 * Collection helpers shared by the routes.
 *
 * Every list here filters drafts and sorts deterministically, so two builds of
 * the same content produce byte-identical output — which keeps deploy diffs
 * meaningful and makes "did anything actually change?" answerable.
 */

const live = <T extends { data: { draft: boolean } }>(entries: T[]): T[] =>
  entries.filter((e) => !e.data.draft);

const byDate = (a: CollectionEntry<'posts'>, b: CollectionEntry<'posts'>): number => {
  const at = a.data.publishDate?.getTime() ?? 0;
  const bt = b.data.publishDate?.getTime() ?? 0;
  if (at !== bt) return bt - at;
  return a.id.localeCompare(b.id);
};

export async function allPosts(): Promise<CollectionEntry<'posts'>[]> {
  return live(await getCollection('posts')).sort(byDate);
}

/** Services and locations are a local-business concept. Short-circuiting on
 *  site type keeps an informational build from ever touching those collections
 *  (and from warning about them being empty). */
export async function allServices(): Promise<CollectionEntry<'services'>[]> {
  if (!isLocal) return [];
  return live(await getCollection('services')).sort(
    (a, b) => a.data.order - b.data.order || a.id.localeCompare(b.id),
  );
}

export async function allLocations(): Promise<CollectionEntry<'locations'>[]> {
  if (!isLocal) return [];
  return live(await getCollection('locations')).sort(
    (a, b) => a.data.order - b.data.order || a.id.localeCompare(b.id),
  );
}

/**
 * Optional core page — absent is the normal case, so callers fall back to
 * site.config.json. Filtered from the whole collection rather than fetched by
 * id: `getEntry` logs a "not found" warning on every miss, which would mean a
 * wall of noise in the deploy log for pages that were never meant to exist.
 */
export async function corePage(id: string): Promise<CollectionEntry<'pages'> | undefined> {
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

/** Same category, excluding the current post; falls back to newest so the
 *  related rail is never empty on a thin site. */
export function relatedTo(
  post: CollectionEntry<'posts'>,
  posts: CollectionEntry<'posts'>[],
  limit = 3,
): CollectionEntry<'posts'>[] {
  const others = posts.filter((p) => p.id !== post.id);
  const same = others.filter((p) => p.data.category === post.data.category);
  return [...same, ...others.filter((p) => !same.includes(p))].slice(0, limit);
}
