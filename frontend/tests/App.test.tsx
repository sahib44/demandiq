import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../src/App';
import { SAMPLE_DATASET, SAMPLE_RUN } from '../src/components/Activation';
import * as fixtures from './fixtures';

const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });
let calls: { path: string; body?: Record<string, unknown>; method: string }[];
let activated: boolean;
let failPreview: boolean;

function backend(input: string | URL | Request, options?: RequestInit): Promise<Response> {
  const url = new URL(String(input), 'http://localhost');
  const path = url.pathname.replace(/^\/api/, '');
  const body = options?.body ? JSON.parse(String(options.body)) : undefined;
  calls.push({ path: path + url.search, body, method: options?.method || 'GET' });
  if (path.endsWith('/export'))
    return Promise.resolve(
      new Response('stock_code,point\nSYNTH-A,50\n', { headers: { 'Content-Type': 'text/csv' } }),
    );
  if (path === '/inventory/preview')
    return Promise.resolve(
      failPreview
        ? json({ error: { code: 'validation_error', message: 'PRIVATE-RAW-MARKER' } }, 422)
        : json(fixtures.preview(body?.on_hand as number)),
    );
  if (options?.method === 'POST') {
    if (path === '/inventory/scenarios') activated = true;
    return Promise.resolve(
      json({
        job_id: '00000000-0000-4000-8000-000000000001',
        kind: path === '/inventory/scenarios' ? 'inventory' : 'forecasting',
        status: 'succeeded',
        attempts: 1,
        max_attempts: 3,
        error_code: null,
        result:
          path === '/forecasts'
            ? { forecast_id: body?.scope === 'one_week' ? fixtures.IDS.one : fixtures.IDS.retro }
            : path === '/datasets/import'
              ? { dataset_id: body?.dataset_id || fixtures.IDS.dataset }
              : path === '/training-runs'
                ? { run_id: body?.run_id, dataset_id: body?.dataset_id }
                : { scenario_id: fixtures.IDS.scenario },
      }),
    );
  }
  if (path === '/dashboard/context')
    return Promise.resolve(json(activated ? fixtures.context : fixtures.emptyContext));
  if (path === '/datasets') return Promise.resolve(json(activated ? [fixtures.dataset] : []));
  if (path === '/training-runs') return Promise.resolve(json(activated ? [fixtures.run] : []));
  if (path === `/datasets/${fixtures.IDS.dataset}/quality`)
    return Promise.resolve(json(fixtures.quality));
  if (path.startsWith('/dashboard/forecasts/'))
    return Promise.resolve(
      json(
        fixtures.forecastDetail(
          url.searchParams.get('stock_code') || undefined,
          path.includes(fixtures.IDS.one) ? 'one_week' : 'retrospective',
        ),
      ),
    );
  if (path === `/dashboard/runs/${fixtures.IDS.run}`)
    return Promise.resolve(json(fixtures.runDetail));
  if (path === '/inventory/scenarios')
    return Promise.resolve(
      json([fixtures.scenario, { ...fixtures.scenario, scenario_id: fixtures.IDS.second }]),
    );
  if (path.startsWith('/dashboard/scenarios/'))
    return Promise.resolve(json(fixtures.scenarioDetail));
  return Promise.resolve(json({ error: { code: 'not_found' } }, 404));
}

beforeEach(() => {
  calls = [];
  activated = true;
  failPreview = false;
  vi.stubGlobal('fetch', vi.fn(backend));
});
async function navigate(label: string) {
  await userEvent.click(screen.getByRole('link', { name: label }));
  fireEvent(window, new HashChangeEvent('hashchange'));
}

describe('workspace pages connected to typed API results', () => {
  it('labels the fictional public demo instead of implying real retail results', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: string, options?: RequestInit) => {
        if (new URL(input, 'http://localhost').pathname === '/api/dashboard/context')
          return Promise.resolve(
            json({
              ...fixtures.context,
              products: fixtures.context.products.map((product, index) => ({
                ...product,
                stock_code: `SYNTH-${index + 1}`,
              })),
            }),
          );
        return backend(input, options);
      }),
    );
    render(<App />);
    expect(await screen.findByText('Synthetic demonstration data')).toBeVisible();
    expect(screen.getByRole('note')).toHaveTextContent('not evidence of real model performance');
  });
  it.each(['Activate historical sample', 'Import dataset', 'Load frozen run'])(
    'selects successful %s output after an explicit different dataset/run selection',
    async (action) => {
      const otherDataset = '9'.repeat(64),
        otherRun = '8'.repeat(64);
      vi.stubGlobal(
        'fetch',
        vi.fn((input: string, options?: RequestInit) => {
          const url = new URL(input, 'http://localhost');
          const selectedDataset = url.searchParams.get('dataset_id') || fixtures.IDS.dataset;
          const defaultRun =
            selectedDataset === otherDataset
              ? otherRun
              : selectedDataset === SAMPLE_DATASET
                ? SAMPLE_RUN
                : fixtures.IDS.run;
          if (url.pathname === '/api/datasets')
            return Promise.resolve(
              json([
                fixtures.dataset,
                { ...fixtures.dataset, dataset_id: otherDataset },
                { ...fixtures.dataset, dataset_id: SAMPLE_DATASET },
              ]),
            );
          if (url.pathname === '/api/training-runs' && options?.method !== 'POST')
            return Promise.resolve(
              json([{ ...fixtures.run, dataset_id: selectedDataset, run_id: defaultRun }]),
            );
          if (url.pathname === '/api/dashboard/context') {
            calls.push({ path: '/dashboard/context' + url.search, method: 'GET' });
            return Promise.resolve(
              json({
                ...fixtures.context,
                dataset: { ...fixtures.dataset, dataset_id: selectedDataset },
                run: {
                  ...fixtures.run,
                  dataset_id: selectedDataset,
                  run_id: url.searchParams.get('run_id') || defaultRun,
                },
              }),
            );
          }
          return backend(input, options);
        }),
      );
      render(<App />);
      await screen.findByRole('heading', { name: 'A clearer view of demand.' });
      await userEvent.selectOptions(
        screen.getByRole('combobox', { name: 'DATASET' }),
        otherDataset,
      );
      await waitFor(() =>
        expect(screen.getByRole('combobox', { name: 'FROZEN RUN' })).toHaveValue(otherRun),
      );
      await userEvent.selectOptions(screen.getByRole('combobox', { name: 'FROZEN RUN' }), otherRun);
      await waitFor(() =>
        expect(calls.some((call) => call.path.includes(`run_id=${otherRun}`))).toBe(true),
      );
      await userEvent.click(screen.getByRole('button', { name: 'Activate data' }));
      const dialog = screen.getByRole('dialog');
      if (action !== 'Activate historical sample')
        await userEvent.click(within(dialog).getByText('Import a dataset or load another run'));
      await userEvent.click(within(dialog).getByRole('button', { name: action }));
      await within(dialog).findByText('Workspace updated');
      await waitFor(() => {
        const latest = calls.filter((call) => call.path.startsWith('/dashboard/context')).at(-1)!;
        const params = new URL(latest.path, 'http://localhost').searchParams;
        expect(params.get('dataset_id')).toBe(SAMPLE_DATASET);
        expect(params.get('run_id')).toBe(action === 'Import dataset' ? null : SAMPLE_RUN);
      });
      expect(
        calls
          .filter((call) => call.path.startsWith('/training-runs?'))
          .every((call) => call.path.includes('dataset_id=')),
      ).toBe(true);
    },
  );
  it('describes equal final-test WAPE as tied rather than an improvement', async () => {
    const detail = structuredClone(fixtures.runDetail);
    detail.metrics.test.overall.find((row) => row.model === 'moving_average_4')!.wape = 20;
    vi.stubGlobal(
      'fetch',
      vi.fn((input: string, options?: RequestInit) =>
        String(input).includes('/dashboard/runs/')
          ? Promise.resolve(json(detail))
          : backend(input, options),
      ),
    );
    window.location.hash = '/performance';
    render(<App />);
    expect(await screen.findByText(/tied the best simple baseline/)).toHaveTextContent(
      '20% versus 20%',
    );
    expect(screen.queryByText(/beat the best simple baseline/)).not.toBeInTheDocument();
  });
  it('renders real-response overview KPIs with explicit historical and simulation labels', async () => {
    render(<App />);
    expect(
      await screen.findByRole('heading', { name: 'A clearer view of demand.' }),
    ).toBeInTheDocument();
    expect(screen.getByText('125', { selector: '.metric-value' })).toBeInTheDocument();
    expect(screen.getByText('86%', { selector: '.metric-value' })).toBeInTheDocument();
    expect(screen.getByText(/inventory outcomes are simulated/i)).toBeInTheDocument();
    expect(screen.getByText(/not realized company savings/i)).toBeInTheDocument();
    expect(screen.getAllByRole('link', { current: 'page' })).toHaveLength(1);
  });
  it('shows loading instead of fabricated placeholder KPIs', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise<Response>(() => {})),
    );
    render(<App />);
    expect(screen.getByRole('status')).toHaveTextContent('Loading verified workspace data');
    expect(screen.queryByText('Forecasted units')).not.toBeInTheDocument();
  });
  it('handles backend outages without exposing raw response messages', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve(
          json({ error: { code: 'database_unavailable', message: 'PRIVATE-RAW-MARKER' } }, 503),
        ),
      ),
    );
    render(<App />);
    expect(await screen.findByRole('alert')).toHaveTextContent('The database is unavailable');
    expect(screen.queryByText(/PRIVATE-RAW-MARKER/)).not.toBeInTheDocument();
  });
  it('shows an honest empty workspace and completes the five-job sample activation', async () => {
    activated = false;
    render(<App />);
    expect(
      await screen.findByRole('heading', { name: 'Your workspace starts with data' }),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Activate data' }));
    const dialog = screen.getByRole('dialog');
    await userEvent.click(
      within(dialog).getByRole('button', { name: 'Activate historical sample' }),
    );
    expect(await within(dialog).findByText('Workspace updated')).toBeInTheDocument();
    expect(calls.filter((call) => call.method === 'POST').map((call) => call.path)).toEqual([
      '/datasets/import',
      '/training-runs',
      '/forecasts',
      '/forecasts',
      '/inventory/scenarios',
    ]);
    expect(calls.some((call) => /evaluate/.test(call.path))).toBe(false);
    await userEvent.click(within(dialog).getByRole('button', { name: 'Close workspace setup' }));
    expect(await screen.findByText('125', { selector: '.metric-value' })).toBeInTheDocument();
  });
  it('renders quality decisions and filters the training-selected cohort', async () => {
    window.location.hash = '/data-quality';
    render(<App />);
    expect(
      await screen.findByRole('heading', { name: 'Trust starts at the source.' }),
    ).toBeInTheDocument();
    expect(await screen.findByText('Accepted records')).toBeInTheDocument();
    await userEvent.type(screen.getByRole('textbox', { name: 'Filter selected products' }), 'blue');
    const table = screen.getByRole('table', { name: 'Products selected from training history' });
    expect(within(table).getByText('Synthetic blue bowl')).toBeInTheDocument();
    expect(within(table).queryByText('Synthetic amber cup')).not.toBeInTheDocument();
  });
  it('changes product and scope using verified forecast endpoints', async () => {
    window.location.hash = '/forecasts';
    render(<App />);
    const select = await screen.findByRole('combobox', { name: 'Product' });
    await userEvent.selectOptions(select, 'SYNTH-B');
    expect(await screen.findByRole('heading', { name: 'Synthetic blue bowl' })).toBeInTheDocument();
    expect(screen.getByText('70', { selector: '.metric-value' })).toBeInTheDocument();
    expect(calls.some((call) => call.path.includes('stock_code=SYNTH-B'))).toBe(true);
    await userEvent.selectOptions(
      screen.getByRole('combobox', { name: 'Forecast scope' }),
      'one_week',
    );
    expect(
      await screen.findByText('Historical inference · actual unavailable'),
    ).toBeInTheDocument();
    expect(screen.getByText(/No observed actuals or test metrics/)).toBeInTheDocument();
  });
  it('deep-links to the requested planner product rather than falling back to overview', async () => {
    window.location.hash = '/inventory?product=SYNTH-B';
    render(<App />);
    const select = await screen.findByRole('combobox', { name: 'Planner product' });
    expect(select).toHaveValue('SYNTH-B');
    expect(
      screen.getByRole('heading', { name: 'Turn a forecast into a decision.' }),
    ).toBeInTheDocument();
    expect(calls.some((call) => call.path.includes('stock_code=SYNTH-B'))).toBe(true);
  });
  it('updates recommendations from server responses and default service input is valid', async () => {
    window.location.hash = '/inventory';
    render(<App />);
    expect(
      await screen.findByText('60', { selector: '.recommendation-hero strong' }),
    ).toBeInTheDocument();
    const service = screen.getByRole('spinbutton', {
      name: 'Desired service level',
    }) as HTMLInputElement;
    expect(service.checkValidity()).toBe(true);
    const stock = screen.getByRole('spinbutton', { name: 'On-hand inventory' });
    await userEvent.clear(stock);
    await userEvent.type(stock, '99');
    expect(
      await screen.findByText('11', { selector: '.recommendation-hero strong' }),
    ).toBeInTheDocument();
    const latest = calls.filter((call) => call.path === '/inventory/preview').at(-1);
    expect(latest?.body?.on_hand).toBe(99);
    expect(screen.getByText(/Economic inputs score costs/)).toBeInTheDocument();
  });
  it('clears a prior recommendation when preview validation fails', async () => {
    window.location.hash = '/inventory';
    render(<App />);
    await screen.findByText('60', { selector: '.recommendation-hero strong' });
    failPreview = true;
    const stock = screen.getByRole('spinbutton', { name: 'On-hand inventory' });
    await userEvent.clear(stock);
    await userEvent.type(stock, '100');
    expect(await screen.findByRole('alert')).toHaveTextContent('Check the entered values');
    expect(
      screen.queryByText('60', { selector: '.recommendation-hero strong' }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/PRIVATE-RAW-MARKER/)).not.toBeInTheDocument();
  });
  it('submits a simulation with shared parameters and selected-product stock override', async () => {
    window.location.hash = '/inventory';
    render(<App />);
    await screen.findByText('60', { selector: '.recommendation-hero strong' });
    await userEvent.click(screen.getByRole('button', { name: 'Run inventory simulation' }));
    await waitFor(() =>
      expect(
        calls.some((call) => call.path === '/inventory/scenarios' && call.method === 'POST'),
      ).toBe(true),
    );
    const config = calls.find(
      (call) => call.path === '/inventory/scenarios' && call.method === 'POST',
    )?.body?.config as {
      defaults: { service_level: number };
      products: { 'SYNTH-A': { initial_on_hand: number } };
    };
    expect(config.defaults.service_level).toBe(0.95);
    expect(config.products['SYNTH-A'].initial_on_hand).toBe(20);
  });
  it('changes the matched policy comparison and exposes real CSV controls', async () => {
    window.location.hash = '/scenarios';
    render(<App />);
    expect(await screen.findByText('£15', { selector: '.metric-value' })).toBeInTheDocument();
    await userEvent.selectOptions(
      screen.getByRole('combobox', { name: 'Baseline policy' }),
      'previous_demand',
    );
    expect(screen.getByText('£40', { selector: '.metric-value' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Recommendations CSV' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Weekly results CSV' })).toBeInTheDocument();
    expect(screen.getByText(/not achieved savings/)).toBeInTheDocument();
  });
  it('separates selection and final test percentages and reports negative baseline comparison', async () => {
    window.location.hash = '/performance';
    render(<App />);
    expect(await screen.findByText('20%', { selector: '.metric-value' })).toBeInTheDocument();
    expect(screen.getByText(/did not beat/)).toHaveTextContent('20% versus 19%');
    await userEvent.click(screen.getByRole('tab', { name: 'Selection validation' }));
    expect(screen.getByText('10%', { selector: '.metric-value' })).toBeInTheDocument();
    expect(screen.queryByText('1,000%', { selector: '.metric-value' })).not.toBeInTheDocument();
    expect(
      screen.getByText('75%', { selector: '.uncertainty-highlight strong' }),
    ).toBeInTheDocument();
  });
  it('downloads forecast CSV from the real export route, not generated browser rows', async () => {
    const clicked = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    const create = vi.fn(() => 'blob:synthetic-export');
    vi.stubGlobal(
      'URL',
      class extends URL {
        static createObjectURL = create;
        static revokeObjectURL = vi.fn();
      },
    );
    window.location.hash = '/forecasts';
    render(<App />);
    await userEvent.click(await screen.findByRole('button', { name: 'Export CSV' }));
    await waitFor(() => expect(clicked).toHaveBeenCalled());
    expect(calls.some((call) => call.path === `/forecasts/${fixtures.IDS.retro}/export`)).toBe(
      true,
    );
    expect(create).toHaveBeenCalledWith(expect.any(Blob));
  });
  it('provides all six semantic navigation links and an accessible mobile menu state', async () => {
    render(<App />);
    await screen.findByRole('heading', { name: 'A clearer view of demand.' });
    expect(
      within(screen.getByRole('navigation', { name: 'Main navigation' })).getAllByRole('link'),
    ).toHaveLength(6);
    const menu = screen.getByRole('button', { name: 'Open navigation' });
    await userEvent.click(menu);
    expect(menu).toHaveAttribute('aria-expanded', 'true');
    await navigate('Model performance');
    expect(
      await screen.findByRole('heading', { name: 'Evidence before confidence.' }),
    ).toBeInTheDocument();
  });
});
