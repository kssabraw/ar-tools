import { site, has, hasAddress } from './site';

/**
 * Deterministic JSON-LD. Built from facts only — never from generated prose —
 * so a page can never claim something the business hasn't told us.
 *
 * Two rules worth keeping in mind when editing:
 *  1. `telephone` is always `phoneReal`, never the displayed/CallRail number,
 *     so structured data stays consistent with the business's citations.
 *  2. Missing facts are omitted, not emitted empty. A service-area business
 *     with no street address gets `areaServed` and no `address` block.
 */

type Json = Record<string, unknown>;

const prune = (obj: Json): Json =>
  Object.fromEntries(
    Object.entries(obj).filter(([, v]) => (Array.isArray(v) ? v.length > 0 : has(v) || v === true)),
  );

export function organization(): Json {
  const b = site.business;
  return prune({
    '@type': b.name ? 'LocalBusiness' : 'Organization',
    name: b.name || site.siteName,
    legalName: b.legalName,
    url: site.url,
    email: b.email,
    telephone: b.phoneReal,
    description: site.description,
    address: hasAddress()
      ? prune({
          '@type': 'PostalAddress',
          streetAddress: b.street,
          addressLocality: b.city,
          addressRegion: b.region,
          postalCode: b.postalCode,
          addressCountry: b.country,
        })
      : has(b.city)
        ? prune({
            '@type': 'PostalAddress',
            addressLocality: b.city,
            addressRegion: b.region,
            addressCountry: b.country,
          })
        : undefined,
    areaServed: b.areaServed,
    openingHours: b.hours,
  });
}

export function webSite(): Json {
  return {
    '@type': 'WebSite',
    name: site.siteName,
    url: site.url,
    description: site.description,
  };
}

export function article(input: {
  title: string;
  description?: string;
  url: string;
  published?: Date;
  updated?: Date;
  author?: string;
  image?: string;
}): Json {
  return prune({
    '@type': 'Article',
    headline: input.title,
    description: input.description,
    url: input.url,
    datePublished: input.published?.toISOString(),
    dateModified: (input.updated ?? input.published)?.toISOString(),
    author: input.author ? { '@type': 'Person', name: input.author } : undefined,
    image: input.image,
    publisher: organization(),
  });
}

export function service(input: { title: string; description?: string; url: string }): Json {
  return prune({
    '@type': 'Service',
    name: input.title,
    description: input.description,
    url: input.url,
    provider: organization(),
    areaServed: site.business.areaServed,
  });
}

/** Wraps one or more nodes in a single @graph document. */
export function graph(...nodes: Json[]): string {
  return JSON.stringify({ '@context': 'https://schema.org', '@graph': nodes.filter(Boolean) });
}
