// @ts-check
import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';
import site from './site.config.json' with { type: 'json' };

// The site URL drives canonical tags, sitemap and RSS. The provisioner rewrites
// site.config.json's `url` when the custom domain is attached; until then it is
// the *.workers.dev staging URL.
export default defineConfig({
  site: site.url,
  integrations: [sitemap()],
  build: { format: 'directory' },
  devToolbar: { enabled: false },
});
