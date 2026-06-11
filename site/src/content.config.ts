import { defineCollection } from 'astro:content';
import { glob } from 'astro/loaders';
import { z } from 'astro/zod';

const blog = defineCollection({
	// The generator only ever writes plain Markdown.
	loader: glob({ base: './src/content/blog', pattern: '**/*.md' }),
	// Type-check frontmatter using a schema
	schema: z.object({
		title: z.string(),
		description: z.string(),
		// Transform string to Date object
		pubDate: z.coerce.date(),
		tags: z.array(z.string()).default([]),
		summary: z.string().optional(),
		issue: z.number().optional(),
		requestedBy: z.string().optional(),
		model: z.string().optional(),
	}),
});

export const collections = { blog };
