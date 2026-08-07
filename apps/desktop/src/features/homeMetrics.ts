// Home — the honest reading of a list command.
//
// WHY THIS EXISTS. Every count on the dashboard used to be written as
// `state.data?.length ?? 0`. That single `?? 0` collapses four genuinely different
// situations into one number the owner reads as fact:
//
//   · the read has not finished        → the page knows nothing yet
//   · the read was refused / failed    → the page knows nothing and something is wrong
//   · the read resolved with no rows   → the page knows there is nothing
//   · the read resolved with rows      → the page knows the count
//
// Rendered as `0`, a permission refusal on `list_approvals` is indistinguishable from
// "no approvals are waiting". That is the expensive failure mode: a real fault reads as
// a calm empty system and therefore never gets fixed. The same `?? 0` also silently
// turned a failed read into a 0 % ratio (`0 / 0` guarded to `null`, but a partial read
// into a confident percentage).
//
// This module is the pure, testable half of the fix: it turns an `AsyncState` into a
// four-way `Reading` that the page must destructure, so "no data yet" and "could not
// read" cannot be rendered the same way by accident. It computes nothing the backend
// did not return — a `Reading` never invents a fallback value.

import type { AsyncState } from '../hooks/useAsync';

/**
 * What the page actually knows about one number.
 *
 * `empty` exists only for quantities that are undefined over an empty set (a ratio has
 * no value when its denominator is 0). A *count* over an empty set is a real `value` of
 * 0 — that distinction is the whole point, so it is encoded in the types.
 */
export type Reading<T> =
  | { kind: 'loading' }
  | { kind: 'unreadable'; error: string }
  | { kind: 'empty' }
  | { kind: 'value'; value: T };

/**
 * The reason attached when a read settled without an error and without data. Tauri's
 * list commands return arrays; `null` here means the boundary handed back nothing, so
 * the page has established no rows and must not claim zero of them.
 */
export const NO_DATA_RETURNED = 'the read returned no data';

/**
 * Reduce one list read to what is actually known.
 *
 * Order matters and is deliberate:
 *  1. an error wins even when stale rows are still in `data` — showing yesterday's rows
 *     under today's failed read is the same lie in a different shape;
 *  2. present data (including `[]`) is a real value, even while a reload is in flight,
 *     so a refresh does not blank the dashboard;
 *  3. no data + in flight is `loading`;
 *  4. no data + settled is unreadable, not zero.
 */
export function readList<T>(state: AsyncState<T[]>): Reading<T[]> {
  if (state.error) return { kind: 'unreadable', error: state.error };
  if (state.data !== null) return { kind: 'value', value: state.data };
  if (state.loading) return { kind: 'loading' };
  return { kind: 'unreadable', error: NO_DATA_RETURNED };
}

/** Map a reading's value without disturbing the other three states. */
export function mapReading<A, B>(r: Reading<A>, f: (value: A) => B): Reading<B> {
  return r.kind === 'value' ? { kind: 'value', value: f(r.value) } : r;
}

/** How many rows the read established. Zero rows is a value, not an absence. */
export function countOf<T>(state: AsyncState<T[]>): Reading<number> {
  return mapReading(readList(state), (rows) => rows.length);
}

/**
 * A whole-percent share of the rows that match `predicate`.
 *
 * Over zero rows the share is genuinely undefined, so this returns `empty` — the page
 * renders that as "no data yet", which is not what it renders for `unreadable`.
 */
export function percentOf<T>(
  state: AsyncState<T[]>,
  predicate: (row: T) => boolean,
): Reading<number> {
  const r = readList(state);
  if (r.kind !== 'value') return r;
  const total = r.value.length;
  if (total === 0) return { kind: 'empty' };
  const hits = r.value.filter(predicate).length;
  return { kind: 'value', value: Math.round((hits / total) * 100) };
}

/** True when the page failed to establish this number at all. Used to keep the hero
 *  power-mark from painting "live" over a dashboard that could not read its workspace. */
export function isUnreadable(r: Reading<unknown>): boolean {
  return r.kind === 'unreadable';
}
