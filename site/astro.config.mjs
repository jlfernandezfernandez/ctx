// @ts-check

import mdx from '@astrojs/mdx';
import sitemap from '@astrojs/sitemap';
import { defineConfig } from 'astro/config';

// https://astro.build/config
export default defineConfig({
	site: 'https://jlfernandezfernandez.github.io',
	base: '/ctx',
	integrations: [mdx(), sitemap()],
	markdown: {
		shikiConfig: {
			theme: 'github-dark-default',
		},
	},
});
