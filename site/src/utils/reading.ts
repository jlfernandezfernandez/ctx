// Client-side "read" tracking, stored under a single localStorage key.
// All functions are pure (operate on the raw string) so they are trivially testable
// without a DOM or localStorage.

export const KEY = 'ctx-reading';

type Reading = { read: string[]; days: string[] };

// Fresh mutable object each call — markRead mutates read/days in place.
const empty = (): Reading => ({ read: [], days: [] });

export function parseReading(raw: string | null): Reading {
	if (!raw) return empty();
	try {
		const v = JSON.parse(raw);
		const read = Array.isArray(v?.read) ? v.read.filter((s: unknown) => typeof s === 'string') : [];
		// `days` = distinct YYYY-MM-DD with at least one read article; backs the weekly heatmap.
		const days = Array.isArray(v?.days) ? v.days.filter((s: unknown) => typeof s === 'string') : [];
		return { read, days };
	} catch {
		// ponytail: corrupt JSON = empty state, never throw on the client
		return empty();
	}
}

export function markRead(raw: string | null, slug: string, today: string): string {
	const reading = parseReading(raw);
	if (!reading.read.includes(slug)) reading.read.push(slug);
	if (!reading.days.includes(today)) reading.days.push(today);
	return JSON.stringify(reading);
}
