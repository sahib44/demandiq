import { act, renderHook, waitFor } from '@testing-library/react';
import { spawnSync } from 'node:child_process';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { expect, it, vi } from 'vitest';
import { ApiError, downloadCsv, query, request, waitForJob } from '../src/api/client';
import { number, percent } from '../src/components/format';
import { useResource } from '../src/hooks/useResource';
import type { Job } from '../src/types/api';

it('encodes bounded query values and omits absent filters', () => {
  expect(query('/products', { stock_code: 'A & B', run_id: null })).toBe(
    '/products?stock_code=A+%26+B',
  );
});
it('maps transport failures to a safe actionable public error', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(() => Promise.reject(new Error('SECRET-PRIVATE-DSN'))),
  );
  await expect(request('/datasets')).rejects.toBeInstanceOf(ApiError);
  await expect(request('/datasets')).rejects.not.toThrow(/SECRET/);
});
it('redacts malformed successful proxy responses instead of displaying parser excerpts', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(() => Promise.resolve(new Response('<html>SECRET-PRIVATE-HTML</html>'))),
  );
  await expect(request('/datasets')).rejects.toMatchObject({ code: 'invalid_response' });
  await expect(request('/datasets')).rejects.not.toThrow(/SECRET/);
});
it('refuses an HTML error page masquerading as a successful CSV download', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(() =>
      Promise.resolve(
        new Response('<html>SECRET-PRIVATE-HTML</html>', {
          headers: { 'Content-Type': 'text/html' },
        }),
      ),
    ),
  );
  await expect(downloadCsv('/forecasts/id/export', 'forecast.csv')).rejects.toMatchObject({
    code: 'invalid_export',
  });
});
it('does not display nonfinite or missing quantities as measured zeros', () => {
  expect(number(null)).toBe('—');
  expect(number(Infinity)).toBe('—');
  expect(percent(null)).toBe('—');
  expect(percent(0.8)).toBe('80%');
});
it.each(['America/New_York', 'Pacific/Auckland'])(
  'preserves naive source dates in %s while respecting explicit timestamp offsets',
  (timezone) => {
    const source = pathToFileURL(resolve('src/components/format.ts')).href;
    const result = spawnSync(
      process.execPath,
      [
        '--input-type=module',
        '--eval',
        `import { date } from ${JSON.stringify(source)}; console.log(JSON.stringify([date('2011-12-09T23:30:00'), date('2011-12-09T00:15:00'), date('2011-12-09T23:30:00-05:00')]));`,
      ],
      { encoding: 'utf8', env: { ...process.env, TZ: timezone } },
    );
    expect(result.status, result.stderr).toBe(0);
    expect(JSON.parse(result.stdout)).toEqual([
      '9 December 2011',
      '9 December 2011',
      '10 December 2011',
    ]);
  },
);
it('ignores late successful responses from an aborted product request', async () => {
  const pending = new Map<string, (value: Response) => void>();
  const signals = new Map<string, AbortSignal>();
  vi.stubGlobal(
    'fetch',
    vi.fn((path: string, options: RequestInit) => {
      signals.set(path, options.signal as AbortSignal);
      return new Promise<Response>((resolve) => pending.set(path, resolve));
    }),
  );
  const hook = renderHook(({ path }) => useResource<{ product: string }>(path), {
    initialProps: { path: '/product/A' },
  });
  hook.rerender({ path: '/product/B' });
  expect(signals.get('/api/product/A')?.aborted).toBe(true);
  await act(async () =>
    pending.get('/api/product/B')!(new Response(JSON.stringify({ product: 'B' }))),
  );
  await waitFor(() => expect(hook.result.current.data?.product).toBe('B'));
  await act(async () =>
    pending.get('/api/product/A')!(new Response(JSON.stringify({ product: 'A' }))),
  );
  expect(hook.result.current.data?.product).toBe('B');
});
it('polls queued jobs through running to success without resubmitting work', async () => {
  vi.useFakeTimers();
  const initial: Job = {
    job_id: '00000000-0000-4000-8000-000000000001',
    kind: 'training',
    status: 'queued',
    attempts: 0,
    max_attempts: 3,
    error_code: null,
    result: null,
  };
  const updates: string[] = [];
  let call = 0;
  const fetcher = vi.fn((_path: string) =>
    Promise.resolve(
      new Response(
        JSON.stringify({
          ...initial,
          status: ++call === 1 ? 'running' : 'succeeded',
          attempts: 1,
          result: call === 2 ? { run_id: 'a'.repeat(64) } : null,
        }),
      ),
    ),
  );
  vi.stubGlobal('fetch', fetcher);
  try {
    const promise = waitForJob(
      initial,
      (job) => updates.push(job.status),
      new AbortController().signal,
    );
    await vi.advanceTimersByTimeAsync(2000);
    expect((await promise).status).toBe('succeeded');
    expect(updates).toEqual(['queued', 'running', 'succeeded']);
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(fetcher.mock.calls.every((args) => String(args[0]).includes('/jobs/'))).toBe(true);
  } finally {
    vi.useRealTimers();
  }
});
it('reports permanent worker failures with a safe code and stops polling', async () => {
  const job: Job = {
    job_id: '00000000-0000-4000-8000-000000000001',
    kind: 'training',
    status: 'failed',
    attempts: 3,
    max_attempts: 3,
    error_code: 'artifact_integrity',
    result: null,
  };
  const fetcher = vi.fn();
  vi.stubGlobal('fetch', fetcher);
  await expect(waitForJob(job, vi.fn(), new AbortController().signal)).rejects.toMatchObject({
    code: 'artifact_integrity',
  });
  expect(fetcher).not.toHaveBeenCalled();
});
