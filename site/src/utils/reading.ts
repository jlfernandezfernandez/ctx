// Client-side "read" tracking, stored under a single localStorage key.
// All functions are pure (operate on the raw string) so they are trivially testable
// without a DOM or localStorage.

export const KEY = 'ctx-reading';

type Streak = { current: number; longest: number; last_read_date: string | null };

export function parseReading(raw: string | null): { read: string[]; streak: Streak } {
	const empty = { read: [] as string[], streak: { current: 0, longest: 0, last_read_date: null } };
	if (!raw) return empty;
	try {
		const v = JSON.parse(raw);
		const read = Array.isArray(v?.read) ? v.read.filter((s: unknown) => typeof s === 'string') : [];
		const s = v?.streak;
		return {
			read,
			streak: {
				current: typeof s?.current === 'number' ? s.current : 0,
				longest: typeof s?.longest === 'number' ? s.longest : 0,
				last_read_date: typeof s?.last_read_date === 'string' ? s.last_read_date : null,
			},
		};
	} catch {
		// ponytail: corrupt JSON = empty state, never throw on the client
		return empty;
	}
}

// Business days strictly between two 'YYYY-MM-DD' dates (exclusive both ends).
// Parsed as UTC so the weekday check is timezone-stable.
function businessDaysBetween(last: string, today: string): number {
	let count = 0;
	const d = new Date(last + 'T00:00:00Z');
	const end = new Date(today + 'T00:00:00Z');
	d.setUTCDate(d.getUTCDate() + 1);
	for (; d < end; d.setUTCDate(d.getUTCDate() + 1)) {
		const day = d.getUTCDay();
		if (day !== 0 && day !== 6) count++;
	}
	return count;
}

// Streak rules: +1 on a new day if no business day was skipped (weekends don't
// break it), reset to 1 if a business day was missed, 1 on first read.
export function updateStreak(streak: Streak, today: string): Streak {
	const last = streak.last_read_date;
	if (today === last || (last && today < last)) return streak; // same day = no double-count
	const current = !last ? 1 : businessDaysBetween(last, today) === 0 ? streak.current + 1 : 1;
	return { current, longest: Math.max(streak.longest, current), last_read_date: today };
}

export function markRead(raw: string | null, slug: string, today: string): string {
	const reading = parseReading(raw);
	if (!reading.read.includes(slug)) reading.read.push(slug);
	reading.streak = updateStreak(reading.streak, today);
	return JSON.stringify(reading);
}
