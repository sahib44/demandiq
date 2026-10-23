import { useEffect, useState } from 'react';
import { request } from '../api/client';

export interface Resource<T> {
  data: T | null;
  loading: boolean;
  error: Error | null;
}

export function useResource<T>(path: string | null, revision = 0): Resource<T> {
  const [state, setState] = useState<Resource<T> & { path: string | null }>({
    path,
    data: null,
    loading: !!path,
    error: null,
  });
  useEffect(() => {
    if (!path) {
      setState({ path, data: null, loading: false, error: null });
      return;
    }
    const controller = new AbortController();
    setState({ path, data: null, loading: true, error: null });
    request<T>(path, { signal: controller.signal }).then(
      (data) => {
        if (!controller.signal.aborted) setState({ path, data, loading: false, error: null });
      },
      (error: Error) => {
        if (!controller.signal.aborted) setState({ path, data: null, loading: false, error });
      },
    );
    return () => controller.abort();
  }, [path, revision]);
  return state.path === path ? state : { data: null, loading: !!path, error: null };
}
