import { useState } from 'react';
import { Activity, ShieldCheck } from 'lucide-react';
import { MetricChart } from '../components/Charts';
import { useWorkspace } from '../components/Workspace';
import {
  DataTable,
  EmptyState,
  MetricCard,
  Note,
  PageHeader,
  Panel,
  ResourceState,
} from '../components/UI';
import { date, methodName, number, percent, shortId } from '../components/format';
import { useResource } from '../hooks/useResource';
import type { RunDetail } from '../types/api';

export function Performance() {
  const { context } = useWorkspace();
  const run = context.data?.run;
  const resource = useResource<RunDetail>(run ? `/dashboard/runs/${run.run_id}` : null);
  const [scope, setScope] = useState<'selection' | 'calibration' | 'test'>('test');
  const [metric, setMetric] = useState<'wape' | 'mae' | 'rmse'>('wape');
  const [filter, setFilter] = useState('');
  return (
    <>
      <PageHeader
        eyebrow="Model performance"
        title="Evidence before confidence."
        description="Compare measured results with simple baselines, and keep model selection separate from final evaluation."
      />
      {!run ? (
        <EmptyState title="No frozen model run loaded">
          Activate a training run to inspect its chronological validation, uncertainty calibration,
          and model metadata.
        </EmptyState>
      ) : (
        <ResourceState resource={resource}>
          {(data) => {
            const selected = data.plan.best_ml_family;
            const metrics = data.metrics[scope];
            const selectedMetric = metrics?.overall.find((row) => row.model === selected);
            const baselines =
              metrics?.overall
                .filter(
                  (row) =>
                    ['naive', 'moving_average_4', 'seasonal_naive_4'].includes(row.model) &&
                    row.wape != null,
                )
                .sort((a, b) => a.wape! - b.wape!) || [];
            const best = baselines[0];
            const importance = data.importance[selected] || [];
            const maxImportance = Math.max(...importance.map((row) => row.importance), 1);
            const interval = data.interval_metrics?.overall.find((row) => row.model === selected);
            const products =
              metrics?.by_product.filter(
                (row) =>
                  row.model === selected &&
                  row.stock_code?.toLowerCase().includes(filter.toLowerCase()),
              ) || [];
            return (
              <>
                <div className="scope-strip">
                  <ShieldCheck size={18} aria-hidden="true" />
                  <p>
                    <b>{methodName(selected)}</b> was selected using earlier validation. The frozen
                    choice is retained after test access.
                  </p>
                  <span className="subtle-label">Run {shortId(data.run_id)}</span>
                </div>
                <div className="tabs" role="tablist" aria-label="Evaluation scope">
                  {(['selection', 'calibration', 'test'] as const).map((value) => (
                    <button
                      key={value}
                      role="tab"
                      id={`scope-${value}`}
                      aria-controls="scope-results"
                      aria-selected={scope === value}
                      tabIndex={scope === value ? 0 : -1}
                      onKeyDown={(event) => {
                        const choices = ['selection', 'calibration', 'test'] as const;
                        const index = choices.indexOf(value);
                        const next =
                          event.key === 'ArrowRight'
                            ? choices[(index + 1) % 3]
                            : event.key === 'ArrowLeft'
                              ? choices[(index + 2) % 3]
                              : event.key === 'Home'
                                ? choices[0]
                                : event.key === 'End'
                                  ? choices[2]
                                  : null;
                        if (next) {
                          event.preventDefault();
                          setScope(next);
                          document.getElementById(`scope-${next}`)?.focus();
                        }
                      }}
                      onClick={() => setScope(value)}
                    >
                      {value === 'selection'
                        ? 'Selection validation'
                        : value === 'calibration'
                          ? 'Residual calibration'
                          : 'Final test'}
                    </button>
                  ))}
                </div>
                <div id="scope-results" role="tabpanel" aria-labelledby={`scope-${scope}`}>
                  {!metrics ? (
                    <EmptyState title="Completed test is not registered">
                      Load the already-completed retrospective forecast to display its frozen test
                      metrics. No dashboard endpoint evaluates the final test.
                    </EmptyState>
                  ) : (
                    <>
                      <div className="metrics-grid">
                        <MetricCard
                          label={`${scope === 'test' ? 'Final-test' : scope === 'selection' ? 'Selection-validation' : 'Calibration'} WAPE`}
                          value={
                            selectedMetric?.wape == null
                              ? 'Undefined'
                              : `${number(selectedMetric.wape, 2)}%`
                          }
                          detail={methodName(selected)}
                        />
                        <MetricCard
                          label="Mean absolute error"
                          value={number(selectedMetric?.mae, 2)}
                          detail="Units per product-week observation"
                        />
                        <MetricCard
                          label="Forecast bias"
                          value={number(selectedMetric?.bias, 2)}
                          detail="Mean prediction minus actual units"
                        />
                        <MetricCard
                          label="Aligned observations / method"
                          value={number(selectedMetric?.n_observations)}
                          detail={
                            scope === 'selection'
                              ? 'Two expanding validation folds'
                              : scope === 'calibration'
                                ? 'Separate third chronological fold'
                                : 'One completed final test block'
                          }
                        />
                      </div>
                      {scope === 'test' && selectedMetric?.wape != null && best && (
                        <Note tone={selectedMetric.wape > best.wape! ? 'amber' : ''}>
                          {methodName(selected)}{' '}
                          {selectedMetric.wape === best.wape!
                            ? 'tied'
                            : selectedMetric.wape > best.wape!
                              ? 'did not beat'
                              : 'beat'}{' '}
                          the best simple baseline ({methodName(best.model)}) on final-test WAPE:{' '}
                          {number(selectedMetric.wape, 2)}% versus {number(best.wape, 2)}%. This
                          observation does not revise the frozen model choice.
                        </Note>
                      )}
                      <div className="two-column">
                        <Panel
                          title="Every model earns its comparison"
                          subtitle={`${scope === 'test' ? 'Final test' : scope === 'selection' ? 'Selection validation' : 'Calibration'} · lower ${metric.toUpperCase()} is better`}
                          action={
                            <label className="compact-select">
                              <span className="sr-only">Comparison metric</span>
                              <select
                                value={metric}
                                onChange={(event) =>
                                  setMetric(event.target.value as 'wape' | 'mae' | 'rmse')
                                }
                              >
                                <option value="wape">WAPE (%)</option>
                                <option value="mae">MAE (units)</option>
                                <option value="rmse">RMSE (units)</option>
                              </select>
                            </label>
                          }
                        >
                          <MetricChart rows={metrics.overall} metric={metric} />
                        </Panel>
                        <Panel
                          title="Measured model scorecard"
                          subtitle="WAPE / sMAPE are percentages; bias retains its sign"
                        >
                          <DataTable
                            caption={`${scope} model evaluation metrics`}
                            headers={['Method', 'MAE', 'RMSE', 'WAPE', 'sMAPE', 'Bias']}
                          >
                            {metrics.overall.map((row) => (
                              <tr
                                key={row.model}
                                className={row.model === selected ? 'highlight-row' : ''}
                              >
                                <th scope="row">{methodName(row.model)}</th>
                                <td>{number(row.mae, 1)}</td>
                                <td>{number(row.rmse, 1)}</td>
                                <td>
                                  {row.wape == null ? 'Undefined' : `${number(row.wape, 2)}%`}
                                </td>
                                <td>{number(row.smape, 1)}%</td>
                                <td>{number(row.bias, 1)}</td>
                              </tr>
                            ))}
                          </DataTable>
                        </Panel>
                      </div>
                      <div className="two-column">
                        <Panel
                          title="Error across time"
                          subtitle="Selected ML method · chronological observations"
                        >
                          <DataTable
                            caption={`${scope} weekly error for selected model`}
                            headers={['Week', 'Fold', 'MAE', 'WAPE', 'Bias']}
                          >
                            {metrics.by_week
                              .filter((row) => row.model === selected)
                              .map((row) => (
                                <tr key={`${row.fold}-${row.week}`}>
                                  <th scope="row">{date(row.week, true)}</th>
                                  <td>{row.fold}</td>
                                  <td>{number(row.mae, 1)}</td>
                                  <td>
                                    {row.wape == null ? 'Undefined' : `${number(row.wape, 1)}%`}
                                  </td>
                                  <td>{number(row.bias, 1)}</td>
                                </tr>
                              ))}
                          </DataTable>
                        </Panel>
                        <Panel
                          title="Underforecasting & overforecasting"
                          subtitle="Counts and absolute unit magnitudes, shown separately"
                        >
                          <DataTable
                            caption={`${scope} directional forecast errors`}
                            headers={[
                              'Method',
                              'Under count',
                              'Under units',
                              'Over count',
                              'Over units',
                            ]}
                          >
                            {metrics.error_direction.map((row) => (
                              <tr key={row.model}>
                                <th scope="row">{methodName(row.model)}</th>
                                <td>{number(Number(row.underforecast_count))}</td>
                                <td>{number(Number(row.underforecast_units), 1)}</td>
                                <td>{number(Number(row.overforecast_count))}</td>
                                <td>{number(Number(row.overforecast_units), 1)}</td>
                              </tr>
                            ))}
                          </DataTable>
                        </Panel>
                      </div>
                      <Panel
                        title="Error by product"
                        subtitle="Selected model · products evaluated within this scope and fold cohort"
                        action={
                          <label className="compact-select">
                            <span className="sr-only">Filter performance products</span>
                            <input
                              value={filter}
                              onChange={(event) => setFilter(event.target.value)}
                              placeholder="Filter stock codes"
                            />
                          </label>
                        }
                      >
                        <DataTable
                          caption={`${scope} product errors for selected model`}
                          headers={['Stock code', 'Observations', 'MAE', 'RMSE', 'WAPE', 'Bias']}
                        >
                          {products.map((row) => (
                            <tr key={row.stock_code}>
                              <th scope="row">{row.stock_code}</th>
                              <td>{number(row.n_observations)}</td>
                              <td>{number(row.mae, 2)}</td>
                              <td>{number(row.rmse, 2)}</td>
                              <td>{row.wape == null ? 'Undefined' : `${number(row.wape, 2)}%`}</td>
                              <td>{number(row.bias, 2)}</td>
                            </tr>
                          ))}
                        </DataTable>
                      </Panel>
                    </>
                  )}
                </div>
                <div className="two-column">
                  <Panel
                    title="Uncertainty, measured honestly"
                    subtitle="Completed-test empirical interval coverage"
                  >
                    {data.interval_metrics ? (
                      <>
                        <div className="uncertainty-highlight">
                          <Activity size={20} aria-hidden="true" />
                          <strong>{percent(interval?.coverage)}</strong>
                          <span>
                            observed coverage / {percent(interval?.nominal_coverage)} nominal
                          </span>
                        </div>
                        <DataTable
                          caption="Final-test interval calibration results"
                          headers={['Method', 'Coverage', 'Nominal', 'Mean width']}
                        >
                          {data.interval_metrics.overall.map((row) => (
                            <tr key={row.model}>
                              <th scope="row">{methodName(row.model)}</th>
                              <td>{percent(row.coverage)}</td>
                              <td>{percent(row.nominal_coverage)}</td>
                              <td>{number(row.mean_width, 1)}</td>
                            </tr>
                          ))}
                        </DataTable>
                        <p className="small-print">
                          Pooled pre-test residual estimates transfer across products and refitted
                          models. Observed coverage is not a future guarantee.
                        </p>
                      </>
                    ) : (
                      <p className="panel-copy">
                        Uncertainty coverage appears only after completed test predictions are
                        registered.
                      </p>
                    )}
                  </Panel>
                  <Panel
                    title="What the model uses"
                    subtitle={`Native feature importance · ${methodName(selected)}`}
                  >
                    <div className="importance-list">
                      {importance.slice(0, 10).map((row) => (
                        <div key={row.feature}>
                          <div>
                            <span>
                              {row.feature
                                .replace(/^numeric__|^product__/, '')
                                .replaceAll('_', ' ')}
                            </span>
                            <b>{number(row.importance, 3)}</b>
                          </div>
                          <span className="importance-track">
                            <i style={{ width: `${(row.importance / maxImportance) * 100}%` }} />
                          </span>
                        </div>
                      ))}
                    </div>
                    <p className="small-print">
                      Method: {importance[0]?.method.replaceAll('_', ' ') || 'Not available'}.
                      Importance is descriptive, not causal, and scales differ across model
                      families.
                    </p>
                  </Panel>
                </div>
                <Panel
                  title="Frozen model & validation protocol"
                  subtitle="The data and decisions needed to reproduce this run"
                >
                  <dl className="metadata-grid">
                    <div>
                      <dt>Run identifier</dt>
                      <dd className="mono">{data.run_id}</dd>
                    </div>
                    <div>
                      <dt>Dataset identifier</dt>
                      <dd className="mono">{data.dataset_id}</dd>
                    </div>
                    <div>
                      <dt>Final training week</dt>
                      <dd>{date(data.plan.refit_end)}</dd>
                    </div>
                    <div>
                      <dt>Feature count</dt>
                      <dd>{data.plan.features.length}</dd>
                    </div>
                    <div>
                      <dt>Selection block</dt>
                      <dd>
                        {date(
                          String(
                            data.plan.roles.selection_start ||
                              data.metrics.selection.by_week
                                .map((row) => row.week)
                                .filter(Boolean)
                                .sort()[0] ||
                              '',
                          ),
                          true,
                        )}{' '}
                        — {date(String(data.plan.roles.selection_end), true)}
                      </dd>
                    </div>
                    <div>
                      <dt>Calibration block</dt>
                      <dd>
                        {date(String(data.plan.roles.calibration_start), true)} —{' '}
                        {date(String(data.plan.roles.calibration_end), true)}
                      </dd>
                    </div>
                    <div>
                      <dt>Test block</dt>
                      <dd>
                        {date(String(data.plan.roles.test_start), true)} —{' '}
                        {date(String(data.plan.roles.test_end), true)}
                      </dd>
                    </div>
                    <div>
                      <dt>Training timestamp</dt>
                      <dd>{date(String(data.training_metadata.training_timestamp_utc))}</dd>
                    </div>
                  </dl>
                  <details className="chart-data">
                    <summary>View training metadata and feature schema</summary>
                    <pre>
                      {JSON.stringify(
                        { ...data.training_metadata, features: data.plan.features },
                        null,
                        2,
                      )}
                    </pre>
                  </details>
                </Panel>
              </>
            );
          }}
        </ResourceState>
      )}
    </>
  );
}
