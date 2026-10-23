import { useEffect, useRef, useState } from 'react';
import { ArrowRight, LoaderCircle, PackagePlus } from 'lucide-react';
import { query, request, submit, waitForJob } from '../api/client';
import { useWorkspace } from '../components/Workspace';
import {
  EmptyState,
  ExportButton,
  Loading,
  MetricCard,
  Note,
  PageHeader,
  Panel,
} from '../components/UI';
import { date, money, number, percent } from '../components/format';
import { useResource } from '../hooks/useResource';
import type { ForecastDetail, InventoryPreview, Job, Json } from '../types/api';

const defaults = {
  on_hand: '',
  on_order: '0',
  backordered_units: '0',
  lead_time_weeks: '1',
  review_period_weeks: '1',
  service_level: '0.95',
  unit_purchase_cost: '1',
  unit_selling_price: '2',
  holding_cost_per_unit_week: '0.02',
  stockout_penalty_per_unit: '3',
  order_cost: '5',
  min_order_quantity: '0',
  case_pack_size: '1',
  max_inventory_capacity: '',
};
const fields: {
  key: keyof typeof defaults;
  label: string;
  min?: number;
  max?: number;
  step?: string;
  help?: string;
}[] = [
  { key: 'on_hand', label: 'On-hand inventory', min: 0, step: '1' },
  { key: 'on_order', label: 'Units already on order', min: 0, step: '1' },
  { key: 'backordered_units', label: 'Backordered units', min: 0, step: '1' },
  { key: 'lead_time_weeks', label: 'Lead time (weeks)', min: 1, step: '1' },
  { key: 'review_period_weeks', label: 'Review period (weeks)', min: 1, step: '1' },
  {
    key: 'service_level',
    label: 'Desired service level',
    min: 0.001,
    max: 0.999,
    step: '0.001',
    help: 'Normal-approximation input, not a service guarantee.',
  },
  { key: 'holding_cost_per_unit_week', label: 'Holding cost / unit / week', min: 0, step: '0.01' },
  { key: 'stockout_penalty_per_unit', label: 'Stockout penalty / lost unit', min: 0, step: '0.1' },
  { key: 'unit_purchase_cost', label: 'Unit purchase cost', min: 0, step: '0.01' },
  { key: 'unit_selling_price', label: 'Unit selling price', min: 0, step: '0.01' },
  { key: 'order_cost', label: 'Cost per placed order', min: 0, step: '0.1' },
  { key: 'min_order_quantity', label: 'Minimum order quantity', min: 0, step: '1' },
  { key: 'case_pack_size', label: 'Case-pack size', min: 1, step: '1' },
  {
    key: 'max_inventory_capacity',
    label: 'Maximum capacity (optional)',
    min: 0,
    step: '1',
    help: 'On-hand plus all outstanding units reserve capacity.',
  },
];
export function InventoryPlanner() {
  const { context, refresh, activate } = useWorkspace();
  const workspace = context.data;
  const requested = new URLSearchParams(window.location.hash.split('?')[1]).get('product');
  const [product, setProduct] = useState('');
  const selected = product || requested;
  const code = workspace?.products.some((row) => row.stock_code === selected)
    ? selected!
    : workspace?.products[0]?.stock_code;
  const batch = workspace?.one_week_forecast || workspace?.retrospective_forecast;
  const details = useResource<ForecastDetail>(
    batch ? query(`/dashboard/forecasts/${batch.forecast_id}`, { stock_code: code }) : null,
  );
  const [form, setForm] = useState(defaults);
  const [previewResult, setPreview] = useState<{ key: string; value: InventoryPreview } | null>(
    null,
  );
  const [previewing, setPreviewing] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [scenarioError, setScenarioError] = useState<Error | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [running, setRunning] = useState(false);
  const [arrival, setArrival] = useState('');
  useEffect(() => {
    if (details.data)
      setForm({ ...defaults, on_hand: String(details.data.planner_defaults.on_hand) });
  }, [details.data]);
  const parameters: Record<string, Json> = {};
  const state: Record<string, number> = {};
  for (const [key, value] of Object.entries(form)) {
    if (['on_hand', 'on_order', 'backordered_units'].includes(key)) state[key] = Number(value);
    else parameters[key] = value === '' ? null : Number(value);
  }
  const payload = {
    forecast_id: batch?.forecast_id || '',
    stock_code: code || '',
    ...state,
    parameters,
  };
  const serialized = JSON.stringify(payload);
  const preview =
    previewResult?.key === serialized && !details.loading ? previewResult.value : null;
  const simulationController = useRef<AbortController | null>(null);
  useEffect(() => () => simulationController.current?.abort(), []);
  const valid =
    !!batch &&
    !!code &&
    form.on_hand !== '' &&
    Object.values(state).every((value) => Number.isFinite(value) && value >= 0) &&
    Object.entries(parameters).every(
      ([key, value]) =>
        (key === 'max_inventory_capacity' && value === null) ||
        (typeof value === 'number' && Number.isFinite(value)),
    );
  useEffect(() => {
    setPreview(null);
    setError(null);
    if (!valid || details.loading) {
      setPreviewing(false);
      return;
    }
    const controller = new AbortController();
    setPreviewing(true);
    const timer = setTimeout(() => {
      request<InventoryPreview>('/inventory/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: serialized,
        signal: controller.signal,
      }).then(
        (value) => {
          if (!controller.signal.aborted) {
            setPreview({ key: serialized, value });
            setPreviewing(false);
          }
        },
        (error: Error) => {
          if (!controller.signal.aborted) {
            setError(error);
            setPreviewing(false);
          }
        },
      );
    }, 300);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [serialized, valid, details.loading]);
  async function simulate() {
    setScenarioError(null);
    if (!workspace?.retrospective_forecast || !code) return;
    if (state.backordered_units > 0) {
      setScenarioError(
        new Error(
          'The lost-sales simulator requires zero backorders. You can still inspect the planner preview.',
        ),
      );
      return;
    }
    if (state.on_order > 0 && !arrival) {
      setScenarioError(
        new Error(
          'Choose an arrival week for the prepaid on-order units before running the scenario.',
        ),
      );
      return;
    }
    setRunning(true);
    const controller = new AbortController();
    simulationController.current = controller;
    try {
      const config: Record<string, Json> = {
        name: 'dashboard_scenario',
        currency: 'GBP',
        initial_coverage_weeks: 2,
        defaults: parameters,
        products: {
          [code]: {
            initial_on_hand: state.on_hand,
            backordered_units: 0,
            initial_orders: state.on_order > 0 ? [{ week: arrival, quantity: state.on_order }] : [],
          },
        },
      };
      await waitForJob(
        await submit(
          '/inventory/scenarios',
          { forecast_id: workspace.retrospective_forecast.forecast_id, config },
          controller.signal,
        ),
        setJob,
        controller.signal,
      );
      refresh();
      window.location.hash = '/scenarios';
    } catch (error) {
      setScenarioError(error as Error);
    } finally {
      setRunning(false);
    }
  }
  return (
    <>
      <PageHeader
        eyebrow="Inventory planner"
        title="Turn a forecast into a decision."
        description="Adjust stock and business assumptions to see the recommendation update from the verified planning engine."
      />
      {!batch ? (
        <EmptyState
          title="A forecast is needed first"
          action={
            <button className="button primary" onClick={activate}>
              Activate forecasts
            </button>
          }
        >
          Load a frozen forecast to explore assumption-driven inventory recommendations.
        </EmptyState>
      ) : (
        <>
          <div className="filter-bar">
            <label>
              Planner product
              <select value={code || ''} onChange={(event) => setProduct(event.target.value)}>
                {workspace?.products.map((row) => (
                  <option key={row.stock_code} value={row.stock_code}>
                    {row.stock_code} · {row.description || 'Description unavailable'}
                  </option>
                ))}
              </select>
            </label>
            <span className="subtle-label">
              Historical origin · {date(preview?.week || details.data?.features.week)}
            </span>
          </div>
          <div className="planner-layout">
            <Panel
              title="Your inventory assumptions"
              subtitle="Illustrative GBP inputs · no company stock records"
            >
              <form
                className="planner-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  void simulate();
                }}
              >
                <div className="input-grid">
                  {fields.map((field) => (
                    <label key={field.key} htmlFor={`planner-${field.key}`}>
                      {field.label}
                      <input
                        id={`planner-${field.key}`}
                        aria-label={field.label}
                        aria-describedby={field.help ? `planner-${field.key}-help` : undefined}
                        type="number"
                        min={field.min}
                        max={field.max}
                        step={field.step}
                        value={form[field.key]}
                        required={field.key !== 'max_inventory_capacity'}
                        onChange={(event) => setForm({ ...form, [field.key]: event.target.value })}
                      />
                      {field.help && <small id={`planner-${field.key}-help`}>{field.help}</small>}
                    </label>
                  ))}
                </div>
                {Number(form.on_order) > 0 && (
                  <label>
                    On-order arrival week (Monday)
                    <input
                      type="date"
                      value={arrival}
                      onChange={(event) => setArrival(event.target.value)}
                    />
                  </label>
                )}
                <p className="small-print">
                  {details.data?.planner_defaults.label ||
                    'Opening stock is an assumption, not a historical inventory fact.'}{' '}
                  Economic inputs score costs; they do not optimize order quantities.
                </p>
                <button
                  className="button primary full-width"
                  type="submit"
                  disabled={!valid || !preview || running || !workspace?.retrospective_forecast}
                >
                  {running ? (
                    <LoaderCircle size={17} className="spin" aria-hidden="true" />
                  ) : (
                    <PackagePlus size={17} aria-hidden="true" />
                  )}
                  {running ? 'Running simulation…' : 'Run inventory simulation'}
                </button>
                <p className="small-print">
                  Runs every policy across the frozen cohort. These defaults apply to all products;
                  the selected product receives your opening-stock override.
                </p>
                {!workspace?.retrospective_forecast && (
                  <Note>
                    Load the completed retrospective forecast to simulate historical actual demand.
                  </Note>
                )}
                {job && (
                  <p role="status">
                    Simulation {job.status} · attempt {job.attempts} of {job.max_attempts}
                  </p>
                )}
                {scenarioError && (
                  <p className="inline-error" role="alert">
                    {scenarioError.message}
                  </p>
                )}
              </form>
            </Panel>
            <div className="planner-results" aria-live="polite" aria-busy={previewing}>
              {previewing || details.loading ? (
                <Loading label="Updating inventory recommendation…" />
              ) : error ? (
                <div className="error-state" role="alert">
                  {error.message}
                </div>
              ) : preview ? (
                <>
                  <div className="recommendation-hero">
                    <span className="eyebrow">Recommended order</span>
                    <strong>
                      {number(preview.recommendation.recommended_order_quantity)}
                      <small>units</small>
                    </strong>
                    <p>
                      {preview.recommendation.recommended_order_quantity > 0
                        ? 'Stock position is at or below the reorder threshold.'
                        : 'No replenishment order is recommended under these assumptions.'}
                    </p>
                    <ExportButton
                      path="/inventory/preview/export"
                      payload={payload}
                      filename="inventory-recommendation.csv"
                    >
                      Export recommendation
                    </ExportButton>
                  </div>
                  <div className="mini-metrics">
                    <MetricCard
                      label="Reorder point"
                      value={number(preview.recommendation.reorder_point, 1)}
                      detail="Lead demand + safety stock"
                    />
                    <MetricCard
                      label="Safety stock"
                      value={number(preview.recommendation.safety_stock, 1)}
                      detail="Normal approximation"
                    />
                    <MetricCard
                      label="Inventory position"
                      value={number(preview.recommendation.inventory_position)}
                      detail="On-hand + on-order − backlog"
                    />
                    <MetricCard
                      label="Approx. stockout risk"
                      value={percent(preview.risk.probability)}
                      detail="Next-week approximation only"
                      tone="amber"
                    />
                  </div>
                  <Panel
                    title="What drives this recommendation"
                    subtitle="Frozen forecast and pre-test calibration errors"
                  >
                    <dl className="summary-list">
                      <div>
                        <dt>One-week point forecast</dt>
                        <dd>{number(preview.recommendation.weekly_forecast, 1)}</dd>
                      </div>
                      <div>
                        <dt>Lead-time demand</dt>
                        <dd>{number(preview.recommendation.lead_time_demand, 1)}</dd>
                      </div>
                      <div>
                        <dt>Target inventory position</dt>
                        <dd>{number(preview.recommendation.target_inventory_position, 1)}</dd>
                      </div>
                    </dl>
                    <ul className="reason-list">
                      {preview.recommendation.reasons.map((reason) => (
                        <li key={reason}>{reason}</li>
                      ))}
                    </ul>
                    <p className="small-print">{preview.recommendation.horizon_assumption}</p>
                  </Panel>
                  <Panel
                    title="Illustrative cost preview"
                    subtitle="Order cash plus approximate next-week operating costs"
                  >
                    <dl className="summary-list">
                      {[
                        'purchase_cost',
                        'order_cost',
                        'holding_cost',
                        'stockout_cost',
                        'total_cost',
                      ].map((key) => (
                        <div key={key}>
                          <dt>{key.replaceAll('_', ' ')}</dt>
                          <dd>
                            {money(
                              typeof preview.cost_preview[key] === 'number'
                                ? (preview.cost_preview[key] as number)
                                : null,
                            )}
                          </dd>
                        </div>
                      ))}
                    </dl>
                    <p className="small-print">{String(preview.cost_preview.label)}</p>
                  </Panel>
                  <Note>{preview.risk.label}</Note>
                  <a className="text-link" href="#/scenarios">
                    Review full historical simulations
                    <ArrowRight size={15} aria-hidden="true" />
                  </a>
                </>
              ) : (
                <Note>
                  Enter valid nonnegative stock and business inputs to preview a recommendation.
                </Note>
              )}
            </div>
          </div>
        </>
      )}
    </>
  );
}
