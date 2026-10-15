import { useCallback, useEffect, useState } from "react";

export function errMsg(e: unknown): string {
  return e instanceof Error ? e.message : "Something went wrong";
}

/** Run an async loader whenever `deps` change; `reload()` re-runs it. */
export function useAsync<T>(load: () => Promise<T>, deps: unknown[]) {
  const [state, setState] = useState<{ data?: T; error?: string; loading: boolean }>({ loading: true });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    setState((s) => ({ data: s.data, loading: true }));
    load()
      .then((data) => alive && setState({ data, loading: false }))
      .catch((e) => alive && setState({ loading: false, error: errMsg(e) }));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { ...state, reload };
}
