import assert from 'node:assert/strict';
import { test } from 'node:test';
import { markRead, parseReading, updateStreak } from './reading.ts';

const ZERO = { current: 0, longest: 0, last_read_date: null };

test('parseReading: empty localStorage', () => {
	assert.deepEqual(parseReading(null), { read: [], streak: ZERO });
});

test('parseReading: corrupt JSON', () => {
	assert.deepEqual(parseReading('{not json'), { read: [], streak: ZERO });
});

test('parseReading: missing/invalid read field', () => {
	assert.deepEqual(parseReading('{}'), { read: [], streak: ZERO });
	assert.deepEqual(parseReading('{"read":"nope"}'), { read: [], streak: ZERO });
});

test('parseReading: filters non-string entries', () => {
	assert.deepEqual(parseReading('{"read":["a",1,null,"b"]}').read, ['a', 'b']);
});

test('parseReading: invalid streak fields fall back to defaults', () => {
	assert.deepEqual(parseReading('{"streak":{"current":"x"}}').streak, ZERO);
});

test('parseReading: reads stored streak', () => {
	const raw = '{"streak":{"current":7,"longest":12,"last_read_date":"2026-06-16"}}';
	assert.deepEqual(parseReading(raw).streak, { current: 7, longest: 12, last_read_date: '2026-06-16' });
});

test('markRead: adds slug to empty state', () => {
	assert.deepEqual(parseReading(markRead(null, 'slug-1', '2026-06-16')).read, ['slug-1']);
});

test('markRead: no duplicates', () => {
	const once = markRead(null, 'slug-1', '2026-06-16');
	const twice = markRead(once, 'slug-1', '2026-06-17');
	assert.deepEqual(parseReading(twice).read, ['slug-1']);
});

test('markRead: appends to existing', () => {
	const raw = markRead(markRead(null, 'a', '2026-06-16'), 'b', '2026-06-16');
	assert.deepEqual(parseReading(raw).read, ['a', 'b']);
});

test('markRead: recovers from corrupt state', () => {
	assert.deepEqual(parseReading(markRead('garbage', 'a', '2026-06-16')).read, ['a']);
});

// Streak rules. Dates: 2026-06-15 Mon, 16 Tue, 17 Wed, 19 Fri, 22 Mon.

test('updateStreak: first read starts at 1', () => {
	assert.deepEqual(updateStreak(ZERO, '2026-06-16'), {
		current: 1,
		longest: 1,
		last_read_date: '2026-06-16',
	});
});

test('updateStreak: consecutive business day increments', () => {
	const mon = updateStreak(ZERO, '2026-06-15');
	const tue = updateStreak(mon, '2026-06-16');
	assert.equal(tue.current, 2);
	assert.equal(tue.longest, 2);
});

test('updateStreak: same day does not double-count', () => {
	const tue = updateStreak(ZERO, '2026-06-16');
	assert.deepEqual(updateStreak(tue, '2026-06-16'), tue);
});

test('updateStreak: skipped business day resets to 1', () => {
	const mon = updateStreak(ZERO, '2026-06-15'); // skip Tue
	const wed = updateStreak(mon, '2026-06-17');
	assert.equal(wed.current, 1);
});

test('updateStreak: weekend does not break streak (Fri -> Mon)', () => {
	const fri = { current: 4, longest: 4, last_read_date: '2026-06-19' };
	const mon = updateStreak(fri, '2026-06-22');
	assert.equal(mon.current, 5);
});

test('updateStreak: longest survives a reset', () => {
	const high = { current: 7, longest: 7, last_read_date: '2026-06-15' };
	const reset = updateStreak(high, '2026-06-17'); // skipped Tue -> reset
	assert.equal(reset.current, 1);
	assert.equal(reset.longest, 7);
});

test('updateStreak: ignores dates before last_read_date', () => {
	const tue = updateStreak(ZERO, '2026-06-16');
	assert.deepEqual(updateStreak(tue, '2026-06-15'), tue);
});
