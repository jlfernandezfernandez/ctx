// @ts-check

import mdx from '@astrojs/mdx';
import sitemap from '@astrojs/sitemap';
import { defineConfig } from 'astro/config';

// https://astro.build/config
export default defineConfig({
	site: 'https://jlfernandezfernandez.github.io',
	base: '/ctx',
	redirects: {
		// Astro does not prepend `base` to redirect destinations.
		'/como-funciona': '/ctx/how-it-works',
	},
	integrations: [mdx(), sitemap()],
	markdown: {
		shikiConfig: {
			theme: 'github-dark-default',
		},
	},
});
