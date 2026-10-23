import { ArrowRight, CalendarDays, Search } from 'lucide-react';
import { useState } from 'react';
import { useWorkspace } from '../components/Workspace';
import { CostChart, DemandChart } from '../components/Charts';
import {
  DataTable,
  EmptyState,
  ExportButton,
  MetricCard,
  Note,
  PageHeader,
  Panel,
  ResourceState,
  ViewLink,
} from '../components/UI';
import { date, methodName, money, number, percent } from '../components/format';
import { useResource } from '../hooks/useResource';
import type { ScenarioDetail } from '../types/api';

export function Overview() {
  const { context, activate } = useWorkspace();
  const data = context.data;
  const overview = data?.overview;
  const [search, setSearch] = useState('');
  const scenario = useResource<ScenarioDetail>(
    data?.scenario ? `/dashboard/scenarios/${data.scenario.scenario_id}` : null,
  );
  const policy = overview?.scenario_policy;
  const currency = data?.scenario?.summary.currency || 'GBP';
  const risk =
    overview?.risk_products.filter((row) =>
      `${row.stock_code} ${data?.products.find((product) => product.stock_code === row.stock_code)?.description || ''}`
        .toLowerCase()
        .includes(search.toLowerCase()),
    ) || [];
  return (
    <>
      <PageHeader
        eyebrow="Executive overview"
        title="A clearer view of demand."
        description="See what’s forecast, where inventory falls short, and how your assumptions shape the outcome."
        actions={
          <div className="date-chip">
            <CalendarDays size={15} aria-hidden="true" />
            {overview?.forecast_week
              ? `Origin ${date(overview.forecast_week, true)} ${overview.forecast_week.slice(0, 4)}`
              : 'Historical workspace'}
          </div>
        }
      />
      {!data?.run ? (
        <EmptyState
          title="Your workspace starts with data"
          action={
            <button className="button primary" onClick={activate}>
              Activate historical sample
              <ArrowRight size={16} aria-hidden="true" />
            </button>
          }
        >
          Activate a verified dataset and frozen training run to explore real forecasts and
          inventory simulations.
        </EmptyState>
      ) : (
        <>
          <div className="scope-strip">
            <span className="scope-label">HISTORICAL DEMONSTRATION</span>
            <p>
              {methodName(overview?.selected_ml_family || 'selected model')} ·{' '}
              {data.products.length} training-selected products · inventory outcomes are simulated
            </p>
            <ViewLink href="#/performance">Model evidence</ViewLink>
          </div>
          <div className="metrics-grid">
            <MetricCard
              label="Forecasted units"
              value={number(overview?.forecast_units)}
              detail={`One-week forecast · ${date(overview?.forecast_week, true)}`}
            />
            <MetricCard
              label="Products with stockouts"
              value={number(overview?.products_with_simulated_stockouts)}
              detail="Observed within this inventory simulation"
              tone="amber"
            />
            <MetricCard
              label="Simulated net inventory cost"
              value={money(policy?.net_inventory_cost, currency)}
              detail="Includes closing inventory asset credit"
            />
            <MetricCard
              label="Simulated fill rate"
              value={percent(policy?.fill_rate)}
              detail="Fulfilled units ÷ historical demand"
              tone="teal"
            />
          </div>
          <div className="overview-grid">
            <Panel
              title="Demand served, week by week"
              subtitle="Historical recorded demand and simulated ML-policy fulfillment"
              action={<ViewLink href="#/forecasts">Explore forecasts</ViewLink>}
            >
              <ResourceState resource={scenario}>
                {(value) => {
                  const rows = value.weekly
                    .filter((row) => row.policy === 'ml_safety_stock')
                    .map((row) => ({
                      week: row.week,
                      actual: row.actual,
                      prediction: row.fulfilled_units,
                    }));
                  return (
                    <>
                      <DemandChart rows={rows} predictionLabel="Simulated fulfilled demand" />
                      <details className="chart-data">
                        <summary>View chart data</summary>
                        <DataTable
                          caption="Weekly historical demand and simulated fulfillment"
                          headers={['Week', 'Recorded demand', 'Simulated fulfilled']}
                        >
                          {rows.map((row) => (
                            <tr key={row.week}>
                              <th scope="row">{date(row.week, true)}</th>
                              <td>{number(Number(row.actual))}</td>
                              <td>{number(Number(row.prediction))}</td>
                            </tr>
                          ))}
                        </DataTable>
                      </details>
                    </>
                  );
                }}
              </ResourceState>
              {!data.scenario && (
                <EmptyState title="No simulation yet">
                  Run an inventory scenario to compare fulfillment with historical demand.
                </EmptyState>
              )}
            </Panel>
            <Panel
              title="The inventory trade-off"
              subtitle="ML policy versus matched mean + safety stock"
              className="tradeoff-panel"
            >
              <div className="tradeoff-value">
                <span>Simulated net-cost difference</span>
                <strong>{money(overview?.comparison?.simulated_savings, currency)}</strong>
                <p>
                  {overview?.comparison
                    ? `${number(overview.comparison.simulated_savings_percent == null ? null : Math.abs(overview.comparison.simulated_savings_percent), 2)}% ${overview.comparison.simulated_savings >= 0 ? 'lower' : 'higher'} net cost versus the matched baseline`
                    : 'Run a scenario to compare policies'}
                </p>
              </div>
              <dl className="summary-list">
                <div>
                  <dt>Expected lost units, simulated</dt>
                  <dd>{number(policy?.lost_units)}</dd>
                </div>
                <div>
                  <dt>Gross cash cost</dt>
                  <dd>{money(policy?.gross_cash_cost, currency)}</dd>
                </div>
                <div>
                  <dt>Average on-hand inventory</dt>
                  <dd>{number(policy?.average_inventory, 1)} units</dd>
                </div>
              </dl>
              <p className="small-print">
                Illustrative economics and full terminal recoverability affect this comparison. It
                is not realized company savings.
              </p>
              <ViewLink href="#/scenarios">Compare complete policies</ViewLink>
            </Panel>
          </div>
          <div className="overview-grid lower">
            <Panel
              title="Products that need a closer look"
              subtitle="Ranked by lost units in the historical ML-policy simulation"
              action={
                data.scenario && (
                  <ExportButton
                    path={`/dashboard/scenarios/${data.scenario.scenario_id}/risk/export`}
                    filename="simulated-product-risk.csv"
                  >
                    Risk CSV
                  </ExportButton>
                )
              }
            >
              <div className="table-toolbar">
                <label className="search-input">
                  <Search size={16} aria-hidden="true" />
                  <span className="sr-only">Filter risk products</span>
                  <input
                    placeholder="Search product or stock code"
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                  />
                </label>
                <span>{risk.length} shown</span>
              </div>
              <DataTable
                caption="Historical simulated product stockout risk"
                headers={['Product', 'Lost units', 'Fill rate', 'Stockout weeks', '']}
              >
                {risk.map((row) => (
                  <tr key={row.stock_code}>
                    <th scope="row">
                      <a
                        className="product-link"
                        href={`#/inventory?product=${encodeURIComponent(row.stock_code)}`}
                      >
                        {data.products.find((product) => product.stock_code === row.stock_code)
                          ?.description || row.stock_code}
                      </a>
                      <span className="stock-code">{row.stock_code}</span>
                    </th>
                    <td className={row.lost_units > 0 ? 'text-amber' : ''}>
                      {number(row.lost_units)}
                    </td>
                    <td>{percent(row.fill_rate)}</td>
                    <td>{number(row.stockout_events)}</td>
                    <td>
                      <a
                        className="row-arrow"
                        href={`#/inventory?product=${encodeURIComponent(row.stock_code)}`}
                        aria-label={`Plan inventory for ${row.stock_code}`}
                      >
                        <ArrowRight size={16} />
                      </a>
                    </td>
                  </tr>
                ))}
              </DataTable>
              {!risk.length && <p className="table-empty">No matching product rows.</p>}
            </Panel>
            <Panel
              title="Policy cost comparison"
              subtitle={`Simulated net inventory cost · ${currency}`}
            >
              <ResourceState resource={scenario}>
                {(value) => (
                  <CostChart
                    currency={currency}
                    rows={value.summary.policies.map((row) => ({
                      name: methodName(row.policy),
                      value: row.net_inventory_cost,
                    }))}
                  />
                )}
              </ResourceState>
              <Note>
                Forecast accuracy and business performance answer different questions. Compare the
                frozen model with baselines before interpreting inventory outcomes.
              </Note>
            </Panel>
          </div>
        </>
      )}
    </>
  );
}
