import assert from 'node:assert/strict';
import { test } from 'node:test';
import { markRead, parseReading } from './reading.ts';

const EMPTY = { read: [], days: [] };

test('parseReading: empty localStorage', () => {
	assert.deepEqual(parseReading(null), EMPTY);
});

test('parseReading: corrupt JSON', () => {
	assert.deepEqual(parseReading('{not json'), EMPTY);
});

test('parseReading: missing/invalid read field', () => {
	assert.deepEqual(parseReading('{}'), EMPTY);
	assert.deepEqual(parseReading('{"read":"nope"}'), EMPTY);
});

test('parseReading: missing/invalid days field', () => {
	assert.deepEqual(parseReading('{"read":["a"]}').days, []);
	assert.deepEqual(parseReading('{"days":"nope"}').days, []);
	assert.deepEqual(parseReading('{"days":[1,null,"2026-06-16"]}').days, ['2026-06-16']);
});

test('parseReading: filters non-string entries', () => {
	assert.deepEqual(parseReading('{"read":["a",1,null,"b"]}').read, ['a', 'b']);
});

test('parseReading: reads stored read + days', () => {
	const raw = '{"read":["a"],"days":["2026-06-15","2026-06-16"]}';
	const got = parseReading(raw);
	assert.deepEqual(got.read, ['a']);
	assert.deepEqual(got.days, ['2026-06-15', '2026-06-16']);
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

test('markRead: records the day of the read', () => {
	assert.deepEqual(parseReading(markRead(null, 'a', '2026-06-16')).days, ['2026-06-16']);
});

test('markRead: same day recorded once even with different slugs', () => {
	const raw = markRead(markRead(null, 'a', '2026-06-16'), 'b', '2026-06-16');
	assert.deepEqual(parseReading(raw).days, ['2026-06-16']);
});

test('markRead: distinct days accumulate', () => {
	const raw = markRead(markRead(null, 'a', '2026-06-16'), 'b', '2026-06-17');
	assert.deepEqual(parseReading(raw).days, ['2026-06-16', '2026-06-17']);
});
