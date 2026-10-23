import { useState, type ReactNode } from 'react';
import { AlertCircle, ArrowDownToLine, ArrowUpRight, Inbox, LoaderCircle } from 'lucide-react';
import { ApiError, downloadCsv } from '../api/client';
import type { Resource } from '../hooks/useResource';
import type { Json } from '../types/api';

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow: string;
  title: string;
  description: string;
  actions?: ReactNode;
}) {
  return (
    <header className="page-heading">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p className="page-description">{description}</p>
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  );
}
export function Panel({
  title,
  subtitle,
  action,
  className = '',
  children,
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section className={`panel ${className}`}>
      <div className="panel-heading">
        <div>
          <h2>{title}</h2>
          {subtitle && <p>{subtitle}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}
export function MetricCard({
  label,
  value,
  detail,
  tone,
}: {
  label: string;
  value: string;
  detail: string;
  tone?: string;
}) {
  return (
    <div className={`metric-card ${tone || ''}`}>
      <p className="metric-label">{label}</p>
      <p className="metric-value">{value}</p>
      <p className="metric-detail">{detail}</p>
    </div>
  );
}
export function Note({ children, tone = '' }: { children: ReactNode; tone?: string }) {
  return (
    <div className={`note ${tone}`}>
      <AlertCircle size={16} aria-hidden="true" />
      <div>{children}</div>
    </div>
  );
}
export function EmptyState({
  title,
  children,
  action,
}: {
  title: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <Inbox size={30} aria-hidden="true" />
      <h2>{title}</h2>
      <p>{children}</p>
      {action}
    </div>
  );
}
export function Loading({ label = 'Loading verified workspace data…' }: { label?: string }) {
  return (
    <div className="loading-state" role="status">
      <LoaderCircle className="spin" size={20} aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}
export function ErrorState({ error, retry }: { error: Error; retry?: () => void }) {
  return (
    <div className="error-state" role="alert">
      <AlertCircle size={24} aria-hidden="true" />
      <div>
        <h2>We couldn’t load this view</h2>
        <p>{error.message}</p>
        {error instanceof ApiError && error.requestId && <small>Request {error.requestId}</small>}
        {retry && (
          <button className="button secondary" onClick={retry}>
            Try again
          </button>
        )}
      </div>
    </div>
  );
}
export function ResourceState<T>({
  resource,
  children,
}: {
  resource: Resource<T>;
  children: (data: T) => ReactNode;
}) {
  if (resource.loading) return <Loading />;
  if (resource.error) return <ErrorState error={resource.error} />;
  return resource.data ? children(resource.data) : null;
}
export function ExportButton({
  path,
  filename,
  payload,
  children = 'Export CSV',
}: {
  path: string;
  filename: string;
  payload?: Record<string, Json>;
  children?: ReactNode;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  async function download() {
    setBusy(true);
    setError(null);
    try {
      await downloadCsv(path, filename, payload);
    } catch (error) {
      setError(error as Error);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="export-control">
      <button className="button secondary" disabled={busy} onClick={download}>
        {busy ? (
          <LoaderCircle className="spin" size={16} aria-hidden="true" />
        ) : (
          <ArrowDownToLine size={16} aria-hidden="true" />
        )}
        {children}
      </button>
      {error && (
        <span role="alert" className="inline-error">
          {error.message}
        </span>
      )}
    </div>
  );
}
export function ViewLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a className="text-link" href={href}>
      {children}
      <ArrowUpRight size={15} aria-hidden="true" />
    </a>
  );
}
export function DataTable({
  caption,
  headers,
  children,
}: {
  caption: string;
  headers: string[];
  children: ReactNode;
}) {
  return (
    <div className="table-scroll" role="region" aria-label={`${caption} scroll area`} tabIndex={0}>
      <table>
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            {headers.map((header) => (
              <th key={header} scope="col">
                {header || <span className="sr-only">Actions</span>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}
