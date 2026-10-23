import type { Job, Json } from '../types/api';

export const API_BASE = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '');

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    readonly requestId?: string,
  ) {
    const messages: Record<string, string> = {
      database_unavailable: 'The database is unavailable. Check the API and PostgreSQL services.',
      not_found: 'This resource is unavailable. Refresh the workspace or select another run.',
      validation_error: 'Check the entered values and try again.',
      idempotency_conflict: 'This operation conflicts with an earlier request.',
      artifact_integrity:
        'Artifact verification failed. Preserve the files and inspect the backend.',
      forecast_scope: 'A completed retrospective forecast is required for this simulation.',
    };
    super(messages[code] || 'The request could not be completed. Please try again.');
    this.name = 'ApiError';
  }
}

export function query(path: string, values: Record<string, string | undefined | null>) {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value) params.set(key, value);
  });
  return `${path}${params.size ? `?${params}` : ''}`;
}

async function checked(path: string, options: RequestInit = {}) {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, options);
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiError(0, 'network_unavailable');
  }
  if (!response.ok) {
    let code = 'request_failed';
    try {
      const body = await response.json();
      if (typeof body?.error?.code === 'string') code = body.error.code;
    } catch {
      // Proxy/transport failures may have no JSON body. Never display raw HTML.
    }
    throw new ApiError(response.status, code, response.headers.get('x-request-id') || undefined);
  }
  return response;
}

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await checked(path, options);
  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiError(502, 'invalid_response');
  }
}

export function submit(path: string, payload: Record<string, Json>, signal?: AbortSignal) {
  return request<Job>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID() },
    body: JSON.stringify(payload),
    signal,
  });
}

export async function waitForJob(
  job: Job,
  onUpdate: (value: Job) => void,
  signal: AbortSignal,
): Promise<Job> {
  const deadline = Date.now() + 10 * 60 * 1000;
  let current = job;
  while (!signal.aborted && Date.now() < deadline) {
    onUpdate(current);
    if (current.status === 'succeeded') return current;
    if (current.status === 'failed') throw new ApiError(422, current.error_code || 'job_failed');
    await new Promise<void>((resolve, reject) => {
      const onAbort = () => {
        clearTimeout(timer);
        reject(new DOMException('Aborted', 'AbortError'));
      };
      const timer = setTimeout(() => {
        signal.removeEventListener('abort', onAbort);
        resolve();
      }, 1000);
      signal.addEventListener('abort', onAbort, { once: true });
    });
    current = await request<Job>(`/jobs/${current.job_id}`, { signal });
  }
  if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
  throw new ApiError(408, 'job_timeout');
}

export async function downloadCsv(path: string, filename: string, payload?: Record<string, Json>) {
  const response = await checked(
    path,
    payload
      ? {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        }
      : {},
  );
  if (!response.headers.get('content-type')?.startsWith('text/csv'))
    throw new ApiError(502, 'invalid_export');
  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
