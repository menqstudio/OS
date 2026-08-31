import { describe, it, expect } from 'vitest';
import { established } from './useAsync';

/**
 * `established()` — sixth independent audit, `A-07`.
 *
 * `useAsync` never clears `data`: not on error, and not when its dependencies change. For most
 * consumers that is right — a list blanking out on a failed refresh is worse than a stale one.
 * For a figure that CLAIMS SOMETHING ABOUT NOW it is wrong twice over: on error the last
 * successful value is stated as current forever, and on a dependency change the previous
 * subject's value renders under the new subject's name.
 *
 * The audit found the first half in `RoomReadout`. The second is the worse one and nothing had
 * reported it: switching rooms showed the previous room's participant count, message count and
 * round card, attributed to the room now on screen.
 */
const state = <T>(over: Partial<{ data: T | null; loading: boolean; error: string | null }>) => ({
  data: null as T | null, loading: false, error: null as string | null, ...over,
});

describe('established() — a value only counts when this read produced it', () => {
  it('returns the data of a finished, successful read', () => {
    expect(established(state({ data: [1, 2, 3] }))).toEqual([1, 2, 3]);
  });

  it('an empty result IS established — that is a measured zero', () => {
    // The half that got swapped in RoomReadout: a read that succeeded and returned nothing is a
    // fact, not an absence of one.
    expect(established(state({ data: [] as number[] }))).toEqual([]);
    expect(established(state({ data: 0 }))).toBe(0);
  });

  it('a failed read establishes nothing, even though the stale data is still there', () => {
    expect(established(state({ data: [1, 2, 3], error: 'broker_unavailable' }))).toBeNull();
  });

  it('an in-flight read establishes nothing — this is the misattribution guard', () => {
    // Switching rooms: `data` still holds the PREVIOUS room's value while the new read runs.
    // Returning it here is how the last room's counts get printed under this room's name.
    expect(established(state({ data: [1, 2, 3], loading: true }))).toBeNull();
  });

  it('a first load that has not resolved is null, not an empty result', () => {
    expect(established(state({ data: null, loading: true }))).toBeNull();
  });

  it('distinguishes "read failed" from "read returned nothing"', () => {
    // The single distinction the whole helper exists for, stated as one assertion.
    const measured = established(state({ data: [] as string[] }));
    const unread = established(state({ data: [] as string[], error: 'x' }));
    expect(measured).not.toBe(unread);
    expect(measured).toEqual([]);
    expect(unread).toBeNull();
  });
});
