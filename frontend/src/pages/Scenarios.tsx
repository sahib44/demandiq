import { useState } from 'react';
import { ArrowRight, Search } from 'lucide-react';
import { query } from '../api/client';
import { CostChart } from '../components/Charts';
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
import { date, methodName, money, number, percent, shortId } from '../components/format';
import { useResource } from '../hooks/useResource';
import type { Scenario, ScenarioDetail } from '../types/api';

export function Scenarios() {
  const { context, revision } = useWorkspace();
  const workspace = context.data;
  const [selected, setSelected] = useState('');
  const [comparison, setComparison] = useState('');
  const [baseline, setBaseline] = useState('moving_average_safety_stock');
  const [filter, setFilter] = useState('');
  const list = useResource<Scenario[]>(
    workspace?.retrospective_forecast
      ? query('/inventory/scenarios', {
          forecast_id: workspace.retrospective_forecast.forecast_id,
          limit: '200',
        })
      : null,
    revision,
  );
  const id = list.data?.some((item) => item.scenario_id === selected)
    ? selected
    : workspace?.scenario?.scenario_id;
  const scenario = useResource<ScenarioDetail>(id ? `/dashboard/scenarios/${id}` : null, revision);
  const other = useResource<ScenarioDetail>(
    comparison ? `/dashboard/scenarios/${comparison}` : null,
    revision,
  );
  return (
    <>
      <PageHeader
        eyebrow="Scenario comparison"
        title="Make the trade-offs visible."
        description="Compare complete inventory policies under identical assumptions, then explore sensitivity across configurations."
        actions={
          <a className="button primary" href="#/inventory">
            Configure a scenario
            <ArrowRight size={16} aria-hidden="true" />
          </a>
        }
      />
      {!id ? (
        <EmptyState title="No inventory scenarios yet">
          Open the inventory planner, set your assumptions, and run a historical simulation to
          compare policies.
        </EmptyState>
      ) : (
        <>
          <div className="filter-bar">
            <label>
              Scenario
              <select value={id} onChange={(event) => setSelected(event.target.value)}>
                {list.data?.map((item) => (
                  <option key={item.scenario_id} value={item.scenario_id}>
                    {shortId(item.scenario_id)} · {date(item.created_at, true)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Baseline policy
              <select value={baseline} onChange={(event) => setBaseline(event.target.value)}>
                {[
                  'moving_average_safety_stock',
                  'previous_demand',
                  'moving_average_4',
                  'fixed_reorder_point',
                ].map((name) => (
                  <option key={name} value={name}>
                    {methodName(name)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Compare configuration
              <select value={comparison} onChange={(event) => setComparison(event.target.value)}>
                <option value="">No second configuration</option>
                {list.data
                  ?.filter((item) => item.scenario_id !== id)
                  .map((item) => (
                    <option key={item.scenario_id} value={item.scenario_id}>
                      {shortId(item.scenario_id)} · {date(item.created_at, true)}
                    </option>
                  ))}
              </select>
            </label>
          </div>
          <ResourceState resource={scenario}>
            {(data) => {
              const ml = data.summary.policies.find((row) => row.policy === 'ml_safety_stock');
              const delta = data.summary.comparisons.find(
                (row) => row.baseline_policy === baseline,
              );
              const risk = data.risk_products.filter((row) =>
                row.stock_code.toLowerCase().includes(filter.toLowerCase()),
              );
              const currency = data.summary.currency;
              return (
                <>
                  <div className="scope-strip">
                    <span className="scope-label">RETROSPECTIVE SIMULATION</span>
                    <p>
                      {data.config.name.replaceAll('_', ' ')} ·{' '}
                      {number(data.config.defaults.lead_time_weeks)}-week lead ·{' '}
                      {percent(data.config.defaults.service_level)} desired service level
                    </p>
                  </div>
                  <div className="metrics-grid">
                    <MetricCard
                      label="ML simulated net cost"
                      value={money(ml?.net_inventory_cost, currency)}
                      detail="Closing stock and pipeline credited"
                    />
                    <MetricCard
                      label="Signed simulated cost advantage"
                      value={money(delta?.simulated_savings, currency)}
                      detail={`Versus ${methodName(baseline).toLowerCase()}`}
                      tone={delta && delta.simulated_savings < 0 ? 'amber' : 'teal'}
                    />
                    <MetricCard
                      label="ML simulated fill rate"
                      value={percent(ml?.fill_rate)}
                      detail="Share of historical demand fulfilled"
                    />
                    <MetricCard
                      label="ML average inventory"
                      value={number(ml?.average_inventory, 1)}
                      detail="Mean on-hand units across weeks"
                    />
                  </div>
                  <div className="two-column">
                    <Panel
                      title="Five policies. One set of inputs."
                      subtitle={`Net inventory cost · ${currency} · same starting stock and demand`}
                    >
                      <CostChart
                        currency={currency}
                        rows={data.summary.policies.map((row) => ({
                          name: methodName(row.policy),
                          value: row.net_inventory_cost,
                        }))}
                      />
                    </Panel>
                    <Panel
                      title="Know what the comparison means"
                      subtitle="Business outcomes are assumption-driven"
                    >
                      <dl className="summary-list">
                        <div>
                          <dt>Simulated cost difference</dt>
                          <dd>
                            {delta?.simulated_savings_percent == null
                              ? '—'
                              : `${number(delta.simulated_savings_percent, 2)}%`}
                          </dd>
                        </div>
                        <div>
                          <dt>ML gross cash cost</dt>
                          <dd>{money(ml?.gross_cash_cost, currency)}</dd>
                        </div>
                        <div>
                          <dt>ML stockout events</dt>
                          <dd>{number(ml?.stockout_events)}</dd>
                        </div>
                        <div>
                          <dt>ML lost demand</dt>
                          <dd>{number(ml?.lost_units)} units</dd>
                        </div>
                      </dl>
                      <Note>
                        These are simulated estimates, not achieved savings. Method-specific error
                        buffers and terminal asset credits influence results. Economic inputs score
                        costs; order rules are not cost-optimized.
                      </Note>
                      <p className="small-print">{data.summary.accounting}</p>
                    </Panel>
                  </div>
                  <Panel
                    title="Policy scorecard"
                    subtitle="Fill rate and weekly no-stockout service are distinct measures"
                    action={
                      <ExportButton
                        path={`/inventory/scenarios/${id}/export?kind=summary`}
                        filename="scenario-policy-summary.csv"
                      >
                        Summary CSV
                      </ExportButton>
                    }
                  >
                    <DataTable
                      caption="Inventory policy comparison under identical assumptions"
                      headers={[
                        'Policy',
                        `Net cost (${currency})`,
                        'Gross cash cost',
                        'Fill rate',
                        'Service level',
                        'Lost units',
                        'Average stock',
                      ]}
                    >
                      {data.summary.policies.map((row) => (
                        <tr
                          key={row.policy}
                          className={
                            row.policy === 'ml_safety_stock'
                              ? 'highlight-row'
                              : row.policy === baseline
                                ? 'baseline-row'
                                : ''
                          }
                        >
                          <th scope="row">
                            {methodName(row.policy)}
                            {row.policy === 'ml_safety_stock' && (
                              <span className="stock-code">Frozen selected ML</span>
                            )}
                          </th>
                          <td>{money(row.net_inventory_cost, currency, 2)}</td>
                          <td>{money(row.gross_cash_cost, currency, 2)}</td>
                          <td>{percent(row.fill_rate)}</td>
                          <td>{percent(row.service_level)}</td>
                          <td>{number(row.lost_units)}</td>
                          <td>{number(row.average_inventory, 1)}</td>
                        </tr>
                      ))}
                    </DataTable>
                    <details className="chart-data">
                      <summary>View cost components and inventory accounting</summary>
                      <DataTable
                        caption="Policy inventory cost components"
                        headers={[
                          'Policy',
                          'Purchase cash',
                          'Holding',
                          'Stockout',
                          'Order fees',
                          'Initial asset',
                          'Closing asset',
                        ]}
                      >
                        {data.summary.policies.map((row) => (
                          <tr key={row.policy}>
                            <th scope="row">{methodName(row.policy)}</th>
                            <td>{money(row.purchase_cost, currency, 2)}</td>
                            <td>{money(row.holding_cost, currency, 2)}</td>
                            <td>{money(row.stockout_cost, currency, 2)}</td>
                            <td>{money(row.order_cost, currency, 2)}</td>
                            <td>{money(Number(row.initial_inventory_asset_value), currency)}</td>
                            <td>{money(Number(row.terminal_inventory_asset_value), currency)}</td>
                          </tr>
                        ))}
                      </DataTable>
                    </details>
                  </Panel>
                  {comparison && (
                    <Panel
                      title="Configuration sensitivity"
                      subtitle="Changing assumptions is a sensitivity analysis, not an equal-input policy comparison"
                    >
                      <ResourceState resource={other}>
                        {(second) => {
                          const secondMl = second.summary.policies.find(
                            (row) => row.policy === 'ml_safety_stock',
                          );
                          return (
                            <DataTable
                              caption="ML policy across two scenario configurations"
                              headers={[
                                'Configuration',
                                'Lead weeks',
                                'Holding / unit / week',
                                'Net cost',
                                'Fill rate',
                                'Average inventory',
                              ]}
                            >
                              {[data, second].map((item, index) => {
                                const policy = index === 0 ? ml : secondMl;
                                return (
                                  <tr key={item.scenario_id}>
                                    <th scope="row">
                                      {item.config.name.replaceAll('_', ' ')}
                                      <span className="stock-code">
                                        {shortId(item.scenario_id)}
                                      </span>
                                    </th>
                                    <td>{item.config.defaults.lead_time_weeks}</td>
                                    <td>
                                      {money(
                                        item.config.defaults.holding_cost_per_unit_week,
                                        item.summary.currency,
                                      )}
                                    </td>
                                    <td>
                                      {money(policy?.net_inventory_cost, item.summary.currency)}
                                    </td>
                                    <td>{percent(policy?.fill_rate)}</td>
                                    <td>{number(policy?.average_inventory, 1)}</td>
                                  </tr>
                                );
                              })}
                            </DataTable>
                          );
                        }}
                      </ResourceState>
                    </Panel>
                  )}
                  <div className="two-column">
                    <Panel
                      title="Product outcomes"
                      subtitle="ML policy · historical simulated stockouts"
                      action={
                        <ExportButton
                          path={`/dashboard/scenarios/${id}/risk/export`}
                          filename="simulated-product-risk.csv"
                        >
                          Risk CSV
                        </ExportButton>
                      }
                    >
                      <div className="table-toolbar">
                        <label className="search-input">
                          <Search size={15} aria-hidden="true" />
                          <span className="sr-only">Filter scenario products</span>
                          <input
                            value={filter}
                            onChange={(event) => setFilter(event.target.value)}
                            placeholder="Filter stock codes"
                          />
                        </label>
                        <span>{risk.length} products</span>
                      </div>
                      <DataTable
                        caption="Product outcomes in selected inventory scenario"
                        headers={['Product', 'Lost units', 'Fill rate', 'Stockout weeks']}
                      >
                        {risk.map((row) => (
                          <tr key={row.stock_code}>
                            <th scope="row">{row.stock_code}</th>
                            <td>{number(row.lost_units)}</td>
                            <td>{percent(row.fill_rate)}</td>
                            <td>{number(row.stockout_events)}</td>
                          </tr>
                        ))}
                      </DataTable>
                    </Panel>
                    <Panel
                      title="Reproducible assumptions"
                      subtitle="Every configuration is saved with its scenario"
                    >
                      <dl className="summary-list">
                        {Object.entries(data.config.defaults).map(([key, value]) => (
                          <div key={key}>
                            <dt>{key.replaceAll('_', ' ')}</dt>
                            <dd>{value == null ? 'Not configured' : number(value, 3)}</dd>
                          </div>
                        ))}
                      </dl>
                      <details className="chart-data">
                        <summary>View per-product overrides</summary>
                        <pre>{JSON.stringify(data.config.products, null, 2)}</pre>
                      </details>
                    </Panel>
                  </div>
                  <Panel
                    title="Recorded recommendations"
                    subtitle="Last scheduled ML review per product · not a current purchasing instruction"
                    action={
                      <div className="button-row">
                        <ExportButton
                          path={`/inventory/scenarios/${id}/export`}
                          filename="inventory-recommendations.csv"
                        >
                          Recommendations CSV
                        </ExportButton>
                        <ExportButton
                          path={`/inventory/scenarios/${id}/export?kind=weekly_results`}
                          filename="scenario-weekly-results.csv"
                        >
                          Weekly results CSV
                        </ExportButton>
                      </div>
                    }
                  >
                    <DataTable
                      caption="Last scheduled historical ML recommendations"
                      headers={[
                        'Stock code',
                        'Review week',
                        'Forecast week',
                        'Position',
                        'Reorder point',
                        'Order units',
                      ]}
                    >
                      {data.recommendations.map((row) => (
                        <tr key={String(row.stock_code)}>
                          <th scope="row">{row.stock_code}</th>
                          <td>{date(String(row.week), true)}</td>
                          <td>{date(String(row.forecast_week), true)}</td>
                          <td>{number(Number(row.inventory_position))}</td>
                          <td>{number(Number(row.reorder_point), 1)}</td>
                          <td className="text-teal">
                            {number(Number(row.recommended_order_quantity))}
                          </td>
                        </tr>
                      ))}
                    </DataTable>
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
