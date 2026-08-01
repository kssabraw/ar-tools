import { defineCollection, z } from 'astro:content';
import { glob } from 'astro/loaders';

/**
 * The frontmatter contract between this template and the suite's writers.
 *
 * The field set is not arbitrary: it mirrors what a Claude Design export's
 * repeaters already imply (see docs/modules/website-builder-module-plan-v1_0.md
 * §4.3 — the fixture's `{cat, title, read, photo}` items map onto
 * category/title/readingTime/heroImage). Keep it in sync with
 * services/website_content.py when either side changes.
 */

// Shared across every content type. `jsonld` carries a page-specific
// schema.org object produced by the generator; the layout injects it verbatim,
// so the writers never have to emit <script> tags themselves.
const common = {
  title: z.string(),
  description: z.string().default(''),
  draft: z.boolean().default(false),
  publishDate: z.coerce.date().optional(),
  updatedDate: z.coerce.date().optional(),
  heroImage: z.string().optional(),
  heroImageAlt: z.string().default(''),
  jsonld: z.record(z.any()).optional(),
  // Provenance back to the suite record that produced this file, so a page can
  // be traced (and re-published after reoptimization) without guessing.
  sourceId: z.string().optional(),
};

const posts = defineCollection({
  loader: glob({ pattern: '**/*.md', base: './src/content/posts' }),
  schema: z.object({
    ...common,
    category: z.string().default('General'),
    readingTime: z.string().default(''),
    author: z.string().default(''),
    featured: z.boolean().default(false),
  }),
});

const services = defineCollection({
  loader: glob({ pattern: '**/*.md', base: './src/content/services' }),
  schema: z.object({
    ...common,
    // Short line used on cards/teasers, distinct from the meta description.
    teaser: z.string().default(''),
    order: z.number().default(100),
  }),
});

const locations = defineCollection({
  loader: glob({ pattern: '**/*.md', base: './src/content/locations' }),
  schema: z.object({
    ...common,
    locationName: z.string(),
    teaser: z.string().default(''),
    order: z.number().default(100),
  }),
});

/**
 * Core pages (home/about/contact/privacy). Optional: the template renders
 * sensible defaults from site.config.json when an entry is absent, so a site
 * is never broken just because the core-pages generator hasn't run yet.
 * Entry ids are the route names — `about`, `contact`, `privacy`, `home`.
 */
const pages = defineCollection({
  loader: glob({ pattern: '**/*.md', base: './src/content/pages' }),
  schema: z.object({
    ...common,
    /** Structured section data from the core-pages generator (plan §4.6).
     *  The body is the prose; this carries hero/CTA/slot copy. */
    sections: z.record(z.any()).default({}),
  }),
});

export const collections = { posts, services, locations, pages };
