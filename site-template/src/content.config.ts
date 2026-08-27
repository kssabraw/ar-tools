import { defineCollection, z } from 'astro:content';
import { glob } from 'astro/loaders';

/**
 * The frontmatter contract between this template and the suite's writers.
 *
 * Two rules from the Page Type Reference v3.6 §1.2 shape this file, and both
 * are easy to get wrong:
 *
 *  1. **Page type is declared by the planner, never inferred from the URL.**
 *     Several page types share one URL slot — /{city}/{service}/,
 *     /{city}/{neighborhood}/ and /{city}/{poi}/ are indistinguishable by
 *     shape, as are /{service}/{subservice}/ and /{service}/{brand}/. So every
 *     routed entry declares BOTH its full `path` and its `pageType`, and the
 *     template never parses meaning out of segment count.
 *
 *  2. **Sub-service, neighborhood and hyper-specific pages reuse their
 *     parent's collection** rather than earning their own. A collection is a
 *     content shape, not a page type.
 *
 * Keep in sync with services/website_content.py when either side changes.
 */

const common = {
  title: z.string(),
  description: z.string().default(''),
  draft: z.boolean().default(false),
  publishDate: z.coerce.date().optional(),
  updatedDate: z.coerce.date().optional(),
  heroImage: z.string().optional(),
  heroImageAlt: z.string().default(''),
  // A page-specific schema.org object from the generator; the layout injects it
  // verbatim, so writers never emit <script> tags themselves.
  jsonld: z.record(z.any()).optional(),
  // Back-reference to the suite record that produced this file, so a page can
  // be traced and re-published after reoptimization without guessing.
  sourceId: z.string().optional(),
};

/** Every routed page declares where it lives and what it is. */
const routed = {
  ...common,
  // Full path with leading and trailing slash, e.g. "/anaheim/ac-repair/".
  // Trailing slash on every URL is a ratified convention (reference §1.2).
  path: z.string().regex(/^\/([a-z0-9-]+\/)+$/, 'path must be lowercase, hyphenated, and end in /'),
  pageType: z.enum([
    'service',
    'sub_service',
    'brand_service',
    'location',
    'neighborhood',
    'local_landing',
    'hyper_local',
  ]),
};

/** Services, sub-services and brand × service pages. */
const services = defineCollection({
  loader: glob({ pattern: '**/*.md', base: './src/content/services' }),
  schema: z.object({
    ...routed,
    teaser: z.string().default(''),
    order: z.number().default(100),
    // Set on a sub-service; its breadcrumb parent comes from `path` regardless.
    parentService: z.string().optional(),
  }),
});

/** City pages and neighborhood pages. */
const locations = defineCollection({
  loader: glob({ pattern: '**/*.md', base: './src/content/locations' }),
  schema: z.object({
    ...routed,
    locationName: z.string(),
    teaser: z.string().default(''),
    order: z.number().default(100),
    // Set on a neighborhood page — the city it sits under.
    parentCity: z.string().optional(),
  }),
});

/**
 * The service × city matrix — the SOP's "local landing page", location-first at
 * /{city-slug}/{service-slug}/ (reference §1.1 R1). Its own collection because
 * it is generated from a different axis than either parent, and because a
 * multi-city site has far more of these than anything else.
 */
const localLanding = defineCollection({
  loader: glob({ pattern: '**/*.md', base: './src/content/local-landing' }),
  schema: z.object({
    ...routed,
    citySlug: z.string(),
    serviceSlug: z.string(),
    locationName: z.string(),
    serviceName: z.string(),
    teaser: z.string().default(''),
  }),
});

const posts = defineCollection({
  loader: glob({ pattern: '**/*.md', base: './src/content/posts' }),
  schema: z.object({
    ...common,
    category: z.string().default('General'),
    readingTime: z.string().default(''),
    author: z.string().default(''),
    featured: z.boolean().default(false),
    // Declared at plan time, not writer time (reference §5.3): the format
    // changes the geo rule, the schema, and whether the post counts toward
    // pillar-cluster math. News/Commentary is non-evergreen and excluded.
    format: z
      .enum(['informational_cluster', 'listicle', 'comparison', 'local_geo', 'news'])
      .default('informational_cluster'),
    // Required on the news format: auto-publish plus no human review plus no
    // expiry is how a site ranks on stale information indefinitely.
    reviewBy: z.coerce.date().optional(),
    silo: z.string().optional(),
    cluster: z.string().optional(),
  }),
});

/**
 * Pillar / hub pages (reference §5.3). A pillar is the comprehensive parent of a
 * topic cluster, routed at TOP LEVEL (/{topic-slug}/) — not under /blog/ — so it
 * gets its own collection rather than sharing the flat `posts` shape. Its own
 * `path`/`pageType` are declared for the same reason routed pages carry them:
 * the top-level namespace is shared with services and cities on a geo site, so
 * the template is told the type rather than inferring it. `silo` is the pillar's
 * slug, which its child posts carry too, so the hub can list its cluster.
 */
const pillars = defineCollection({
  loader: glob({ pattern: '**/*.md', base: './src/content/pillars' }),
  schema: z.object({
    ...common,
    path: z.string().regex(/^\/[a-z0-9-]+\/$/, 'pillar path must be a single top-level slug ending in /'),
    pageType: z.literal('pillar'),
    silo: z.string().optional(),
  }),
});

/**
 * Core pages (home/about/contact/privacy). Optional: the template renders
 * defaults from site.config.json when an entry is absent, so a site is never
 * broken because the core-pages generator has not run. Entry ids are the
 * reserved root slugs — `home`, `about-us`, `contact-us`, `privacy-policy`.
 */
const pages = defineCollection({
  loader: glob({ pattern: '**/*.md', base: './src/content/pages' }),
  schema: z.object({
    ...common,
    sections: z.record(z.any()).default({}),
  }),
});

export const collections = { services, locations, localLanding, posts, pages, pillars };
