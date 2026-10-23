import { useState } from 'react';
import { CheckCheck, Search } from 'lucide-react';
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
import { date, number, shortId } from '../components/format';
import { useResource } from '../hooks/useResource';
import type { Quality } from '../types/api';

export function DataQuality() {
  const { context, activate, revision } = useWorkspace();
  const data = context.data;
  const [filter, setFilter] = useState('');
  const quality = useResource<Quality>(
    data?.dataset ? `/datasets/${data.dataset.dataset_id}/quality` : null,
    revision,
  );
  const products =
    data?.products.filter((product) =>
      `${product.stock_code} ${product.description || ''}`
        .toLowerCase()
        .includes(filter.toLowerCase()),
    ) || [];
  return (
    <>
      <PageHeader
        eyebrow="Data foundation"
        title="Trust starts at the source."
        description="Every retained record, rejected value, and cleaning decision has an auditable place."
        actions={
          <button className="button primary" onClick={activate}>
            Import or activate data
          </button>
        }
      />
      {!data?.dataset ? (
        <EmptyState title="No dataset activated">
          Import the official UCI source or activate a verified local dataset to see its quality
          report.
        </EmptyState>
      ) : (
        <ResourceState resource={quality}>
          {(report) => (
            <>
              <div className="source-banner">
                <div className="source-icon">
                  <CheckCheck size={22} aria-hidden="true" />
                </div>
                <div>
                  <strong>Verified dataset · {shortId(data.dataset!.dataset_id)}</strong>
                  <p>
                    {date(report.date_range.start)} — {date(report.date_range.end)} · cleaning
                    version {data.dataset!.cleaning_version}
                  </p>
                </div>
                <span className="scope-label">{data.dataset!.status}</span>
              </div>
              <div className="metrics-grid">
                <MetricCard
                  label="Source records"
                  value={number(report.original_rows)}
                  detail="Before deduplication and validation"
                />
                <MetricCard
                  label="Accepted records"
                  value={number(report.cleaned_rows)}
                  detail="Purchases, cancellations and returns"
                  tone="teal"
                />
                <MetricCard
                  label="Exact duplicates"
                  value={number(report.duplicate_rows)}
                  detail="First typed source occurrence retained"
                />
                <MetricCard
                  label="Rejected records"
                  value={number(report.rejected_rows)}
                  detail="Reasons preserved in the local audit"
                  tone="amber"
                />
              </div>
              <div className="two-column">
                <Panel
                  title="Cleaning, step by step"
                  subtitle="Stage counts reconcile with the original source"
                >
                  <DataTable
                    caption="Dataset cleaning stages"
                    headers={['Stage', 'Before', 'Removed', 'After']}
                  >
                    {report.stages.map((stage) => (
                      <tr key={stage.stage}>
                        <th scope="row">{stage.stage.replaceAll('_', ' ')}</th>
                        <td>{number(stage.before)}</td>
                        <td>{number(stage.removed)}</td>
                        <td>{number(stage.after)}</td>
                      </tr>
                    ))}
                  </DataTable>
                  <div className="panel-stat-row">
                    <span>
                      <b>{number(report.purchase_rows)}</b>purchases
                    </span>
                    <span>
                      <b>{number(report.cancellation_rows)}</b>cancellations
                    </span>
                    <span>
                      <b>{number(report.return_rows)}</b>other returns
                    </span>
                  </div>
                  <Note>
                    C-prefixed negative movements are cancellations. Other negative movements are
                    returns. Credits are not matched to original invoices.
                  </Note>
                </Panel>
                <Panel
                  title="Quality flags & coverage"
                  subtitle="Flags overlap and do not all imply rejected records"
                >
                  <dl className="summary-list">
                    <div>
                      <dt>Missing customer IDs</dt>
                      <dd>{number(report.missing_customer_ids)}</dd>
                    </div>
                    <div>
                      <dt>Missing descriptions</dt>
                      <dd>{number(report.missing_descriptions)}</dd>
                    </div>
                    <div>
                      <dt>Invalid prices</dt>
                      <dd>{number(report.invalid_prices)}</dd>
                    </div>
                    <div>
                      <dt>Invalid quantities</dt>
                      <dd>{number(report.invalid_quantities)}</dd>
                    </div>
                    <div>
                      <dt>Unique products / invoices</dt>
                      <dd>
                        {number(report.unique_products)} / {number(report.unique_invoices)}
                      </dd>
                    </div>
                    <div>
                      <dt>Countries / known customers</dt>
                      <dd>
                        {number(report.unique_countries)} / {number(report.unique_customers)}
                      </dd>
                    </div>
                  </dl>
                  <p className="small-print">
                    Missing optional fields are retained and flagged. Dates and entity counts cover
                    accepted movements. No customer records are shown.
                  </p>
                </Panel>
              </div>
              <Panel
                title="Training-selected product cohort"
                subtitle="Ranked only with pre-test positive purchase volume"
                action={<span className="subtle-label">{products.length} products shown</span>}
              >
                <div className="table-toolbar">
                  <label className="search-input">
                    <Search size={16} aria-hidden="true" />
                    <span className="sr-only">Filter selected products</span>
                    <input
                      value={filter}
                      onChange={(event) => setFilter(event.target.value)}
                      placeholder="Search the selected cohort"
                    />
                  </label>
                </div>
                <DataTable
                  caption="Products selected from training history"
                  headers={['Stock code', 'Description', 'Training units', 'Active training weeks']}
                >
                  {products.map((product) => (
                    <tr key={product.stock_code}>
                      <th scope="row">{product.stock_code}</th>
                      <td>{product.description || 'Description unavailable'}</td>
                      <td>{number(product.training_units)}</td>
                      <td>{number(product.active_training_weeks)}</td>
                    </tr>
                  ))}
                </DataTable>
                {!products.length && (
                  <p className="table-empty">
                    {data.run
                      ? 'No products match your filter.'
                      : 'Load a frozen training run to see its selected cohort.'}
                  </p>
                )}
              </Panel>
              <Panel
                title="Recorded cleaning decisions"
                subtitle="Counts may overlap across reason codes"
              >
                <div className="reason-grid">
                  {Object.entries(report.reason_counts).map(([reason, count]) => (
                    <div key={reason}>
                      <span>{reason.replaceAll('_', ' ')}</span>
                      <b>{number(count)}</b>
                    </div>
                  ))}
                </div>
                <details className="chart-data">
                  <summary>View normalization policies</summary>
                  <dl className="policy-definitions">
                    {Object.entries(report.policies).map(([key, value]) => (
                      <div key={key}>
                        <dt>{key.replaceAll('_', ' ')}</dt>
                        <dd>{typeof value === 'string' ? value : JSON.stringify(value)}</dd>
                      </div>
                    ))}
                  </dl>
                </details>
              </Panel>
            </>
          )}
        </ResourceState>
      )}
    </>
  );
}
