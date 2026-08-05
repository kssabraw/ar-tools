import rss from '@astrojs/rss';
import type { APIContext } from 'astro';
import { allPosts } from '../lib/content';
import { site } from '../lib/site';

export async function GET(context: APIContext) {
  const posts = await allPosts();
  return rss({
    title: site.siteName,
    description: site.description,
    site: context.site ?? site.url,
    items: posts.map((post) => ({
      title: post.data.title,
      description: post.data.description,
      pubDate: post.data.publishDate,
      categories: post.data.category ? [post.data.category] : undefined,
      link: `/blog/${post.id}/`,
    })),
  });
}
