export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
export type NumericRow = { [key: string]: number | string | null };

export interface Dataset {
  dataset_id: string;
  source_sha256: string;
  original_rows: number;
  cleaned_rows: number;
  status: string;
  cleaning_version: string;
  created_at: string;
}
export interface TrainingRun {
  run_id: string;
  dataset_id: string;
  created_at: string;
  config: Record<string, Json>;
}
export interface ForecastBatch {
  forecast_id: string;
  run_id: string;
  scope: 'one_week' | 'retrospective';
  created_at: string;
  metadata_json: Record<string, Json>;
}
export interface Product {
  stock_code: string;
  description: string | null;
  training_units: number;
  active_training_weeks: number;
}
export interface Policy extends NumericRow {
  policy: string;
  fill_rate: number | null;
  service_level: number | null;
  net_inventory_cost: number;
  gross_cash_cost: number;
  lost_units: number;
  average_inventory: number;
  holding_cost: number;
  stockout_cost: number;
  order_cost: number;
  purchase_cost: number;
  stockout_events: number;
  total_demand: number;
  fulfilled_units: number;
}
export interface Comparison {
  baseline_policy: string;
  simulated_savings: number;
  simulated_savings_percent: number | null;
}
export interface ScenarioSummary {
  currency: string;
  policies: Policy[];
  products: (Policy & { stock_code: string })[];
  comparisons: Comparison[];
  accounting: string;
  primary_metric: string;
}
export interface Scenario {
  scenario_id: string;
  forecast_id: string;
  configuration_id: string;
  created_at: string;
  summary: ScenarioSummary;
}
export interface WorkspaceContext {
  dataset: Dataset | null;
  run: TrainingRun | null;
  one_week_forecast: ForecastBatch | null;
  retrospective_forecast: ForecastBatch | null;
  scenario: Scenario | null;
  products: Product[];
  scope: Record<string, Json>;
  overview: {
    forecast_units: number | null;
    forecast_week: string | null;
    forecast_scope: string | null;
    selected_ml_family: string | null;
    scenario_policy: Policy | null;
    comparison: Comparison | null;
    products_with_simulated_stockouts: number | null;
    risk_products: (Policy & { stock_code: string; description?: string | null })[];
  } | null;
}
export interface Quality {
  original_rows: number;
  cleaned_rows: number;
  duplicate_rows: number;
  rejected_rows: number;
  purchase_rows: number;
  cancellation_rows: number;
  return_rows: number;
  missing_descriptions: number;
  missing_customer_ids: number;
  invalid_prices: number;
  invalid_quantities: number;
  unique_products: number;
  unique_invoices: number;
  unique_customers: number;
  unique_countries: number;
  date_range: { start: string | null; end: string | null };
  countries: string[];
  stages: { stage: string; before: number; after: number; removed: number }[];
  reason_counts: Record<string, number>;
  policies: Record<string, Json>;
}
export interface Metric {
  model: string;
  n_observations: number;
  mae: number;
  rmse: number;
  wape: number | null;
  smape: number;
  bias: number;
  stock_code?: string;
  week?: string;
  fold?: string;
  segment?: string;
}
export interface Metrics {
  evaluation_scope: string;
  overall: Metric[];
  by_fold: Metric[];
  by_product: Metric[];
  by_week: Metric[];
  by_segment: Metric[];
  error_direction: (NumericRow & { model: string })[];
}
export interface IntervalMetric {
  model: string;
  n_observations: number;
  coverage: number;
  nominal_coverage: number;
  mean_width: number;
  below_rate: number;
  above_rate: number;
}
export interface RunDetail {
  run_id: string;
  dataset_id: string;
  plan: {
    best_ml_family: string;
    recommended_method: string;
    refit_end: string;
    features: string[];
    roles: Record<string, Json>;
  };
  cohort: Product[];
  importance: Record<string, { feature: string; importance: number; method: string }[]>;
  metrics: { selection: Metrics; calibration: Metrics; test: Metrics | null };
  interval_metrics: { scope: string; overall: IntervalMetric[] } | null;
  training_metadata: Record<string, Json>;
}
export interface ForecastValue {
  stock_code: string;
  week: string;
  method: string;
  point: number;
  lower: number;
  upper: number;
  actual: number | null;
  nominal_coverage: number;
  uncertainty_label: string;
}
export interface ForecastDetail {
  forecast_id: string;
  run_id: string;
  dataset_id: string;
  scope: string;
  selected_ml_family: string;
  product: { stock_code: string; description: string | null };
  history: (NumericRow & { week: string; gross_units: number })[];
  forecasts: ForecastValue[];
  features: { week: string; scope: string; values: Record<string, number | string | null> };
  product_errors: Metric[];
  planner_defaults: { on_hand: number; on_order: number; backordered_units: number; label: string };
}
export interface InventoryParameters {
  lead_time_weeks: number;
  review_period_weeks: number;
  service_level: number;
  unit_purchase_cost: number;
  unit_selling_price: number;
  holding_cost_per_unit_week: number;
  stockout_penalty_per_unit: number;
  order_cost: number;
  min_order_quantity: number;
  case_pack_size: number;
  max_inventory_capacity: number | null;
  fixed_reorder_point?: number | null;
  fixed_target_level?: number | null;
}
export interface InventoryPreview {
  forecast_id: string;
  stock_code: string;
  method: string;
  week: string;
  parameters: InventoryParameters;
  state: { on_hand: number; on_order: number; backordered_units: number };
  recommendation: {
    weekly_forecast: number;
    error_std: number;
    lead_time_demand: number;
    safety_stock: number;
    reorder_point: number;
    target_inventory_position: number;
    inventory_position: number;
    recommended_order_quantity: number;
    reasons: string[];
    horizon_assumption: string;
  };
  risk: { probability: number | null; scope: string; label: string };
  cost_preview: Record<string, Json>;
}
export interface ScenarioDetail {
  scenario_id: string;
  forecast_id: string;
  configuration_id: string;
  config: {
    name: string;
    currency: string;
    initial_coverage_weeks: number;
    defaults: InventoryParameters;
    products: Record<string, Json>;
  };
  summary: ScenarioSummary;
  weekly: (NumericRow & { policy: string; week: string })[];
  risk_products: (Policy & { stock_code: string })[];
  recommendations: NumericRow[];
}
export interface Job {
  job_id: string;
  kind: string;
  status: 'queued' | 'running' | 'succeeded' | 'failed';
  attempts: number;
  max_attempts: number;
  error_code: string | null;
  result: Record<string, Json> | null;
}
