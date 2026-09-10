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

/**
 * FAQPage structured data (reference: the standalone FAQ and the Cost/Comparison
 * pages bind FAQPage). Built from the generated Q&A pairs; an empty set returns
 * undefined so the caller emits no dangling node.
 */
export function faqPage(
  items: { question: string; answer: string }[],
): Json | undefined {
  const entities = (items ?? []).filter((i) => i.question && i.answer);
  if (entities.length === 0) return undefined;
  return {
    '@type': 'FAQPage',
    mainEntity: entities.map((i) => ({
      '@type': 'Question',
      name: i.question,
      acceptedAnswer: { '@type': 'Answer', text: i.answer },
    })),
  };
}

/**
 * Offer structured data (reference §5.1 Offers / Specials — "Offer per card").
 * Built from the operator-entered offer facts only; a card with no title returns
 * undefined so the caller emits no dangling node. `validThrough` is only set when
 * the expiry parses to a real date — freeform expiry text ("Ends this weekend")
 * is left off rather than emitted as an invalid date.
 */
export function offer(input: {
  name: string;
  description?: string;
  url?: string;
  validThrough?: string;
}): Json | undefined {
  if (!input.name) return undefined;
  return prune({
    '@type': 'Offer',
    name: input.name,
    description: input.description,
    url: input.url,
    validThrough: input.validThrough,
    seller: organization(),
  });
}

/**
 * BreadcrumbList built from the URL path, so it can never disagree with the
 * canonical (reference §1.2). Callers pass the crumbs derived by
 * content.breadcrumbsFor; this only shapes them.
 */
export function breadcrumbList(crumbs: { label: string; href: string }[], base: string): Json | undefined {
  if (crumbs.length < 2) return undefined;
  return {
    '@type': 'BreadcrumbList',
    itemListElement: crumbs.map((c, i) => ({
      '@type': 'ListItem',
      position: i + 1,
      name: c.label,
      item: new URL(c.href, base).toString(),
    })),
  };
}

/** Wraps one or more nodes in a single @graph document. */
export function graph(...nodes: Json[]): string {
  return JSON.stringify({ '@context': 'https://schema.org', '@graph': nodes.filter(Boolean) });
}
