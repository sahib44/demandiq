import { useState } from 'react';
import { query } from '../api/client';
import { DemandChart } from '../components/Charts';
import { useWorkspace } from '../components/Workspace';
import {
  DataTable,
  EmptyState,
  ExportButton,
  MetricCard,
  Note,
  PageHeader,
  Panel,
  ResourceState,
} from '../components/UI';
import { date, methodName, number, percent } from '../components/format';
import { useResource } from '../hooks/useResource';
import type { ForecastDetail, NumericRow } from '../types/api';

export function ForecastExplorer() {
  const { context, activate } = useWorkspace();
  const workspace = context.data;
  const [product, setProduct] = useState('');
  const [scope, setScope] = useState<'one_week' | 'retrospective'>('retrospective');
  const [method, setMethod] = useState('');
  const code = workspace?.products.some((item) => item.stock_code === product)
    ? product
    : workspace?.products[0]?.stock_code;
  const batch =
    scope === 'retrospective'
      ? workspace?.retrospective_forecast || workspace?.one_week_forecast
      : workspace?.one_week_forecast;
  const resource = useResource<ForecastDetail>(
    batch ? query(`/dashboard/forecasts/${batch.forecast_id}`, { stock_code: code }) : null,
  );
  return (
    <>
      <PageHeader
        eyebrow="Forecast explorer"
        title="From history to what comes next."
        description="Inspect one-week demand forecasts, empirical intervals, and the evidence behind each prediction."
        actions={
          batch && (
            <ExportButton
              path={`/forecasts/${batch.forecast_id}/export`}
              filename="forecasts.csv"
            />
          )
        }
      />
      {!batch ? (
        <EmptyState
          title="No forecasts available"
          action={
            <button className="button primary" onClick={activate}>
              Activate forecasts
            </button>
          }
        >
          Generate historical one-week inference or load a completed retrospective forecast from
          workspace setup.
        </EmptyState>
      ) : (
        <>
          <div className="filter-bar">
            <label>
              Product
              <select value={code || ''} onChange={(event) => setProduct(event.target.value)}>
                {workspace?.products.map((item) => (
                  <option key={item.stock_code} value={item.stock_code}>
                    {item.stock_code} · {item.description || 'Description unavailable'}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Forecast scope
              <select
                value={batch.scope}
                onChange={(event) => setScope(event.target.value as 'one_week' | 'retrospective')}
              >
                <option value="retrospective" disabled={!workspace?.retrospective_forecast}>
                  Completed historical test
                </option>
                <option value="one_week" disabled={!workspace?.one_week_forecast}>
                  First post-refit origin
                </option>
              </select>
            </label>
            <label>
              Forecast method
              <select
                value={method || workspace?.overview?.selected_ml_family || 'ridge'}
                onChange={(event) => setMethod(event.target.value)}
              >
                {[
                  'ridge',
                  'random_forest',
                  'xgboost',
                  'naive',
                  'moving_average_4',
                  'seasonal_naive_4',
                ].map((name) => (
                  <option key={name} value={name}>
                    {methodName(name)}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <ResourceState resource={resource}>
            {(data) => {
              const selectedMethod = method || data.selected_ml_family;
              const forecastRows = data.forecasts.filter((row) => row.method === selectedMethod);
              const first = forecastRows[0];
              const rows = new Map<string, NumericRow>();
              data.history
                .slice(-12)
                .forEach((row) =>
                  rows.set(row.week, { week: row.week, actual: row.gross_units, prediction: null }),
                );
              forecastRows.forEach((row) =>
                rows.set(row.week, {
                  week: row.week,
                  actual: row.actual,
                  prediction: row.point,
                  lower: row.lower,
                  upper: row.upper,
                  baseline:
                    data.forecasts.find(
                      (other) => other.week === row.week && other.method === 'moving_average_4',
                    )?.point ?? null,
                }),
              );
              return (
                <>
                  <div className="product-heading">
                    <div>
                      <span className="scope-label">{data.product.stock_code}</span>
                      <h2>{data.product.description || 'Product description unavailable'}</h2>
                    </div>
                    <span className="subtle-label">
                      {data.scope === 'retrospective'
                        ? 'Completed test · frozen model'
                        : 'Historical inference · actual unavailable'}
                    </span>
                  </div>
                  <div className="metrics-grid">
                    <MetricCard
                      label={`Forecast · ${date(first?.week, true)}`}
                      value={number(first?.point, 1)}
                      detail={methodName(selectedMethod)}
                    />
                    <MetricCard
                      label="Empirical lower bound"
                      value={number(first?.lower, 1)}
                      detail={`${percent(first?.nominal_coverage)} nominal interval`}
                    />
                    <MetricCard
                      label="Empirical upper bound"
                      value={number(first?.upper, 1)}
                      detail="Coverage is not guaranteed"
                    />
                    <MetricCard
                      label="Last pre-test demand"
                      value={number(data.history.at(-1)?.gross_units)}
                      detail={date(data.history.at(-1)?.week, true)}
                    />
                  </div>
                  <Panel
                    title="Actual demand & forecast"
                    subtitle={`${methodName(selectedMethod)} · weekly gross positive units`}
                  >
                    <DemandChart
                      rows={[...rows.values()].sort((a, b) =>
                        String(a.week).localeCompare(String(b.week)),
                      )}
                      interval
                      comparison
                    />
                    <Note>
                      Intervals use a separate pre-test residual calibration block. Serial
                      dependence, cohort changes and refitting limit reliability; these are
                      empirical ranges, not guarantees.
                    </Note>
                  </Panel>
                  <div className="two-column">
                    <Panel
                      title="Forecast values"
                      subtitle="Recorded actuals are separate from issued predictions"
                    >
                      <DataTable
                        caption="Product weekly forecasts and uncertainty"
                        headers={['Week', 'Actual', 'Forecast', 'Lower', 'Upper']}
                      >
                        {forecastRows.map((row) => (
                          <tr key={row.week}>
                            <th scope="row">{date(row.week, true)}</th>
                            <td>{number(row.actual)}</td>
                            <td className="text-teal">{number(row.point, 1)}</td>
                            <td>{number(row.lower, 1)}</td>
                            <td>{number(row.upper, 1)}</td>
                          </tr>
                        ))}
                      </DataTable>
                    </Panel>
                    <Panel
                      title="Product-level error"
                      subtitle="Completed test only; lower absolute errors are better"
                    >
                      {data.product_errors.length ? (
                        <DataTable
                          caption="Product test error by method"
                          headers={['Method', 'MAE', 'WAPE', 'Bias']}
                        >
                          {data.product_errors.map((row) => (
                            <tr key={row.model}>
                              <th scope="row">{methodName(row.model)}</th>
                              <td>{number(row.mae, 1)}</td>
                              <td>{row.wape == null ? 'Undefined' : `${number(row.wape, 1)}%`}</td>
                              <td>{number(row.bias, 1)}</td>
                            </tr>
                          ))}
                        </DataTable>
                      ) : (
                        <p className="panel-copy">
                          No observed actuals or test metrics are attached to this inference batch.
                        </p>
                      )}
                    </Panel>
                  </div>
                  <Panel
                    title="Causal feature snapshot"
                    subtitle={`First post-refit origin · ${date(data.features.week)} · features use earlier completed weeks`}
                  >
                    <div className="feature-grid">
                      {Object.entries(data.features.values).map(([name, value]) => (
                        <div key={name}>
                          <span>{name.replaceAll('_', ' ')}</span>
                          <b>
                            {typeof value === 'number'
                              ? number(value, 2)
                              : String(value ?? 'Missing')}
                          </b>
                        </div>
                      ))}
                    </div>
                    <p className="small-print">
                      This fixed first-origin snapshot is not a claim that features stay constant
                      across later rolling test weeks.
                    </p>
                  </Panel>
                </>
              );
            }}
          </ResourceState>
        </>
      )}
    </>
  );
}
