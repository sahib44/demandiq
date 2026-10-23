/** Deliberately synthetic UI fixtures. They are never shipped as app results. */
import type { Metrics, Policy, WorkspaceContext } from '../src/types/api';

export const IDS = {
  dataset: 'a'.repeat(64),
  run: 'b'.repeat(64),
  one: 'c'.repeat(64),
  retro: 'd'.repeat(64),
  scenario: 'e'.repeat(64),
  second: 'f'.repeat(64),
};
export const products = [
  {
    stock_code: 'SYNTH-A',
    description: 'Synthetic amber cup',
    training_units: 1000,
    active_training_weeks: 20,
  },
  {
    stock_code: 'SYNTH-B',
    description: 'Synthetic blue bowl',
    training_units: 800,
    active_training_weeks: 18,
  },
];
export const dataset = {
  dataset_id: IDS.dataset,
  source_sha256: '0'.repeat(64),
  original_rows: 100,
  cleaned_rows: 90,
  status: 'ready',
  cleaning_version: '1.0.1',
  created_at: '2026-10-20T12:00:00Z',
};
export const run = {
  run_id: IDS.run,
  dataset_id: IDS.dataset,
  config: {},
  created_at: '2026-10-20T12:00:00Z',
};
export const one = {
  forecast_id: IDS.one,
  run_id: IDS.run,
  scope: 'one_week' as const,
  created_at: '2026-10-20T12:00:00Z',
  metadata_json: {},
};
export const retro = { ...one, forecast_id: IDS.retro, scope: 'retrospective' as const };
export const policies: Policy[] = [
  'previous_demand',
  'moving_average_4',
  'fixed_reorder_point',
  'ml_safety_stock',
  'moving_average_safety_stock',
].map((policy, index) => ({
  policy,
  fill_rate: 0.8 + index * 0.02,
  service_level: 0.75,
  net_inventory_cost: 140 - index * 5,
  gross_cash_cost: 190,
  lost_units: 10,
  average_inventory: 35,
  holding_cost: 4,
  stockout_cost: 10,
  order_cost: 5,
  purchase_cost: 171,
  stockout_events: 2,
  total_demand: 100,
  fulfilled_units: 90,
  initial_inventory_asset_value: 20,
  terminal_inventory_asset_value: 85,
}));
policies[3].net_inventory_cost = 100;
export const summary = {
  currency: 'GBP',
  policies,
  products: products.map((product) => ({ ...policies[3], stock_code: product.stock_code })),
  comparisons: [
    {
      baseline_policy: 'moving_average_safety_stock',
      simulated_savings: 15,
      simulated_savings_percent: 13.04,
    },
    { baseline_policy: 'previous_demand', simulated_savings: 40, simulated_savings_percent: 28.57 },
    {
      baseline_policy: 'moving_average_4',
      simulated_savings: 35,
      simulated_savings_percent: 25.93,
    },
    {
      baseline_policy: 'fixed_reorder_point',
      simulated_savings: 30,
      simulated_savings_percent: 23.08,
    },
  ],
  accounting: 'Synthetic fixture accounting label',
  primary_metric: 'net_inventory_cost',
};
export const scenario = {
  scenario_id: IDS.scenario,
  forecast_id: IDS.retro,
  configuration_id: '1'.repeat(64),
  created_at: '2026-10-20T12:00:00Z',
  summary,
};
export const parameters = {
  lead_time_weeks: 1,
  review_period_weeks: 1,
  service_level: 0.95,
  unit_purchase_cost: 1,
  unit_selling_price: 2,
  holding_cost_per_unit_week: 0.02,
  stockout_penalty_per_unit: 3,
  order_cost: 5,
  min_order_quantity: 0,
  case_pack_size: 1,
  max_inventory_capacity: null,
};
export const scenarioDetail = {
  ...scenario,
  config: {
    name: 'synthetic_fixture',
    currency: 'GBP',
    initial_coverage_weeks: 2,
    defaults: parameters,
    products: {},
  },
  weekly: [{ policy: 'ml_safety_stock', week: '2011-10-10', actual: 100, fulfilled_units: 90 }],
  risk_products: summary.products,
  recommendations: [
    {
      stock_code: 'SYNTH-A',
      week: '2011-11-21',
      forecast_week: '2011-11-28',
      inventory_position: 10,
      reorder_point: 60,
      recommended_order_quantity: 75,
    },
  ],
};
export const context: WorkspaceContext = {
  dataset,
  run,
  one_week_forecast: one,
  retrospective_forecast: retro,
  scenario,
  products,
  scope: { inventory: 'retrospective_simulated_estimates' },
  overview: {
    forecast_units: 125,
    forecast_week: '2011-10-10',
    forecast_scope: 'one_week',
    selected_ml_family: 'ridge',
    scenario_policy: policies[3],
    comparison: summary.comparisons[0],
    products_with_simulated_stockouts: 2,
    risk_products: summary.products,
  },
};
export const emptyContext = {
  ...context,
  dataset: null,
  run: null,
  one_week_forecast: null,
  retrospective_forecast: null,
  scenario: null,
  products: [],
  overview: null,
};
export const quality = {
  original_rows: 100,
  cleaned_rows: 90,
  duplicate_rows: 4,
  rejected_rows: 6,
  purchase_rows: 85,
  cancellation_rows: 5,
  return_rows: 0,
  missing_descriptions: 3,
  missing_customer_ids: 7,
  invalid_prices: 2,
  invalid_quantities: 1,
  unique_products: 2,
  unique_invoices: 30,
  unique_customers: 15,
  unique_countries: 2,
  date_range: { start: '2010-12-01T00:00:00', end: '2011-12-09T00:00:00' },
  countries: ['UK', 'France'],
  stages: [
    { stage: 'source_rows', before: 100, after: 100, removed: 0 },
    { stage: 'exact_source_deduplication', before: 100, after: 96, removed: 4 },
    { stage: 'validation', before: 96, after: 90, removed: 6 },
  ],
  reason_counts: { missing_customer_id: 7, invalid_price: 2 },
  policies: { quantity: 'positive integer purchases' },
};
export const methods = [
  'ridge',
  'random_forest',
  'xgboost',
  'naive',
  'moving_average_4',
  'seasonal_naive_4',
];
export function metrics(scope: string, value = 20): Metrics {
  const overall = methods.map((model, index) => ({
    model,
    n_observations: 16,
    mae: 12 + index,
    rmse: 18 + index,
    wape: model === 'moving_average_4' ? value - 1 : value + index,
    smape: 30,
    bias: -2,
  }));
  return {
    evaluation_scope: scope,
    overall,
    by_fold: overall.map((row) => ({ ...row, fold: '1' })),
    by_product: overall.flatMap((row) =>
      products.map((product) => ({ ...row, stock_code: product.stock_code })),
    ),
    by_week: overall.map((row) => ({
      ...row,
      fold: scope,
      week: scope === 'selection' ? '2011-07-18' : '2011-10-10',
    })),
    by_segment: [],
    error_direction: methods.map((model) => ({
      model,
      underforecast_count: 8,
      overforecast_count: 8,
      underforecast_units: 45,
      overforecast_units: 35,
    })),
  };
}
export const runDetail = {
  run_id: IDS.run,
  dataset_id: IDS.dataset,
  plan: {
    best_ml_family: 'ridge',
    recommended_method: 'ridge',
    refit_end: '2011-10-03',
    features: ['lag1', 'rolling_mean4'],
    roles: {
      selection_start: '2011-07-18',
      selection_end: '2011-09-05',
      calibration_start: '2011-09-12',
      calibration_end: '2011-10-03',
      test_start: '2011-10-10',
      test_end: '2011-11-28',
    },
  },
  cohort: products,
  importance: {
    ridge: [{ feature: 'numeric__lag1', importance: 0.5, method: 'synthetic_fixture_only' }],
  },
  metrics: {
    selection: metrics('selection', 10),
    calibration: metrics('calibration', 15),
    test: metrics('test', 20),
  },
  interval_metrics: {
    scope: 'test',
    overall: methods.map((model) => ({
      model,
      n_observations: 16,
      coverage: 0.75,
      nominal_coverage: 0.8,
      mean_width: 35,
      below_rate: 0.1,
      above_rate: 0.15,
    })),
  },
  training_metadata: { training_timestamp_utc: '2026-10-20T12:00:00Z', seed: 42 },
};
export function forecastDetail(code = 'SYNTH-A', scope = 'retrospective') {
  return {
    forecast_id: scope === 'one_week' ? IDS.one : IDS.retro,
    run_id: IDS.run,
    dataset_id: IDS.dataset,
    scope,
    selected_ml_family: 'ridge',
    product: {
      stock_code: code,
      description: products.find((item) => item.stock_code === code)?.description,
    },
    history: [{ week: '2011-10-03', gross_units: 20 }],
    forecasts: methods.map((method) => ({
      stock_code: code,
      week: '2011-10-10',
      method,
      point: code === 'SYNTH-A' ? 50 : 70,
      lower: 20,
      upper: 100,
      actual: scope === 'one_week' ? null : 45,
      nominal_coverage: 0.8,
      uncertainty_label: 'empirical fixture',
    })),
    features: {
      week: '2011-10-10',
      scope: 'causal_first_post_refit_origin',
      values: { lag1: 20, rolling_mean4: 25 },
    },
    product_errors:
      scope === 'one_week'
        ? []
        : metrics('test').by_product.filter((item) => item.stock_code === code),
    planner_defaults: {
      on_hand: 20,
      on_order: 0,
      backordered_units: 0,
      label: 'Synthetic opening-stock assumption',
    },
  };
}
export function preview(onHand = 20) {
  return {
    forecast_id: IDS.one,
    stock_code: 'SYNTH-A',
    method: 'ridge',
    week: '2011-10-10',
    parameters,
    state: { on_hand: onHand, on_order: 0, backordered_units: 0 },
    recommendation: {
      weekly_forecast: 50,
      error_std: 12,
      lead_time_demand: 50,
      safety_stock: 20,
      reorder_point: 70,
      target_inventory_position: 120,
      inventory_position: onHand,
      recommended_order_quantity: onHand === 99 ? 11 : 60,
      reasons: ['Synthetic fixture response'],
      horizon_assumption: 'Flat carry-forward assumption',
    },
    risk: {
      probability: 0.2,
      scope: 'next_week_normal_approximation',
      label: 'Approximate next-week fixture risk, not a guarantee',
    },
    cost_preview: {
      purchase_cost: 60,
      order_cost: 5,
      holding_cost: 1,
      stockout_cost: 2,
      total_cost: 68,
      label: 'Synthetic order cash plus approximate costs, not realized savings',
    },
  };
}
