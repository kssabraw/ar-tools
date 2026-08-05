import type { APIContext } from 'astro';
import { site } from '../lib/site';

// Generated rather than static so the sitemap URL always matches the site's
// real host, including while it is still on the staging domain.
export function GET(context: APIContext) {
  const base = (context.site ?? new URL(site.url)).toString().replace(/\/$/, '');
  const body = ['User-agent: *', 'Allow: /', '', `Sitemap: ${base}/sitemap-index.xml`, ''].join('\n');
  return new Response(body, { headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
}
