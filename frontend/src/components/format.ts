export const number = (value: number | null | undefined, digits = 0) =>
  value == null || !Number.isFinite(value)
    ? '—'
    : new Intl.NumberFormat('en-GB', { maximumFractionDigits: digits }).format(value);
export const percent = (value: number | null | undefined, digits = 1) =>
  value == null || !Number.isFinite(value) ? '—' : `${number(value * 100, digits)}%`;
export const money = (value: number | null | undefined, currency = 'GBP', digits = 0) =>
  value == null || !Number.isFinite(value)
    ? '—'
    : new Intl.NumberFormat('en-GB', {
        style: 'currency',
        currency: /^[A-Z]{3}$/.test(currency) ? currency : 'GBP',
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      }).format(value);
export function date(value: string | null | undefined, short = false) {
  if (!value) return '—';
  // Source coverage is a naive London wall date, not an instant in the browser's
  // timezone. Timestamps with explicit offsets retain their instant semantics.
  const naive = /^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?$/.test(value);
  const parsed = new Date(naive ? `${value.slice(0, 10)}T00:00:00Z` : value);
  return Number.isNaN(parsed.getTime())
    ? '—'
    : new Intl.DateTimeFormat('en-GB', {
        day: 'numeric',
        month: short ? 'short' : 'long',
        ...(short ? {} : { year: 'numeric' }),
        timeZone: 'UTC',
      }).format(parsed);
}
export const shortId = (id: string | null | undefined) =>
  id ? id.slice(0, 10) : 'No run selected';
export const methodName = (method: string) =>
  ({
    ridge: 'Ridge regression',
    random_forest: 'Random forest',
    xgboost: 'XGBoost',
    naive: 'Last observed demand',
    moving_average_4: 'Four-week mean',
    seasonal_naive_4: 'Four-week recurrence',
    previous_demand: 'Previous demand',
    fixed_reorder_point: 'Fixed reorder point',
    ml_safety_stock: 'ML + safety stock',
    moving_average_safety_stock: 'Mean + safety stock',
  })[method] || method.replaceAll('_', ' ');
