import { useCallback, useEffect, useState } from 'react';

export interface AsyncState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

/**
 * Run an async loader (a real Tauri command call) and expose loading / error /
 * data so screens can render the canonical states. Not a data store or mock
 * layer — it holds only the in-flight request status for one call.
 */
export function useAsync<T>(loader: () => Promise<T>, deps: unknown[] = []): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(loader, deps);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    run()
      .then((v) => {
        if (alive) setData(v);
      })
      .catch((e: unknown) => {
        if (alive) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [run, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, loading, error, reload };
}

/**
 * The value of a read, but ONLY when this read established it. Pure — unit-tested.
 *
 * `useAsync` above never clears `data`: not on error, and not when its dependencies change. Both
 * omissions are deliberate for most consumers — a list that blanks out on a failed refresh is
 * worse than a stale one — and both are wrong for a READOUT OF MEASURED FACTS:
 *
 *   * on error the last successful value stays on screen forever, stated as a current count;
 *   * on a dependency change (switching rooms, projects, conversations) the PREVIOUS subject's
 *     data renders under the new subject's name until the new read lands. That is not stale, it
 *     is **misattributed**, and it is the worse of the two.
 *
 * The sixth independent audit found the first half in `GroupChat`'s `RoomReadout` (`A-07`): after
 * any failed refresh, Messages and Rounds stated a measured `0` for a value nobody had
 * established, because the caller's null guard only held on the very first load.
 *
 * So: a figure counts as established only when the read that produced it has finished, succeeded
 * and produced data. During a load a readout says "not established", which is the honest answer
 * to "how many participants does this room have" while nobody has looked yet.
 *
 * This is NOT a replacement for reading `data` directly. Content — a list, a transcript, a body —
 * is usually better shown stale than blanked. Use this where the value is a CLAIM ABOUT NOW.
 */
export function established<T>(s: AsyncState<T> | {
  data: T | null; loading: boolean; error: string | null;
}): T | null {
  return s.error !== null || s.loading ? null : s.data;
}
