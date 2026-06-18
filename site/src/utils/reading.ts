// Client-side "read" tracking, stored under a single localStorage key.
// All functions are pure (operate on the raw string) so they are trivially testable
// without a DOM or localStorage. The next issue extends the model with `streak`.

export const KEY = 'ctx-reading';

export interface Reading {
	read: string[];
}

export function parseReading(raw: string | null): Reading {
	if (!raw) return { read: [] };
	try {
		const v = JSON.parse(raw);
		const read = Array.isArray(v?.read) ? v.read.filter((s: unknown) => typeof s === 'string') : [];
		return { read };
	} catch {
		// ponytail: corrupt JSON = empty state, never throw on the client
		return { read: [] };
	}
}

export function markRead(raw: string | null, slug: string): string {
	const reading = parseReading(raw);
	if (!reading.read.includes(slug)) reading.read.push(slug);
	return JSON.stringify(reading);
}
