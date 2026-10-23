import { lazy, Suspense, useEffect, useState } from 'react';
import {
  Activity,
  ArrowRight,
  Boxes,
  ChartNoAxesCombined,
  ChevronDown,
  Database,
  LayoutDashboard,
  Menu,
  PanelLeftClose,
  RefreshCw,
  SlidersHorizontal,
  Sparkles,
} from 'lucide-react';
import { Activation } from './components/Activation';
import { WorkspaceProvider, useWorkspace } from './components/Workspace';
import { ErrorState, Loading } from './components/UI';
import { shortId } from './components/format';
import { API_BASE } from './api/client';

const Overview = lazy(() =>
  import('./pages/Overview').then((value) => ({ default: value.Overview })),
);
const DataQuality = lazy(() =>
  import('./pages/DataQuality').then((value) => ({ default: value.DataQuality })),
);
const ForecastExplorer = lazy(() =>
  import('./pages/ForecastExplorer').then((value) => ({ default: value.ForecastExplorer })),
);
const InventoryPlanner = lazy(() =>
  import('./pages/InventoryPlanner').then((value) => ({ default: value.InventoryPlanner })),
);
const Scenarios = lazy(() =>
  import('./pages/Scenarios').then((value) => ({ default: value.Scenarios })),
);
const Performance = lazy(() =>
  import('./pages/Performance').then((value) => ({ default: value.Performance })),
);

const pages = [
  { id: 'overview', label: 'Overview', icon: LayoutDashboard, component: Overview },
  { id: 'data-quality', label: 'Data quality', icon: Database, component: DataQuality },
  {
    id: 'forecasts',
    label: 'Forecast explorer',
    icon: ChartNoAxesCombined,
    component: ForecastExplorer,
  },
  { id: 'inventory', label: 'Inventory planner', icon: Boxes, component: InventoryPlanner },
  { id: 'scenarios', label: 'Scenario comparison', icon: SlidersHorizontal, component: Scenarios },
  { id: 'performance', label: 'Model performance', icon: Activity, component: Performance },
];
function Shell({
  setupOpen,
  setSetupOpen,
}: {
  setupOpen: boolean;
  setSetupOpen: (value: boolean) => void;
}) {
  const [route, setRoute] = useState(window.location.hash.slice(2) || 'overview');
  const [mobileOpen, setMobileOpen] = useState(false);
  const { context, datasets, runs, selectDataset, selectRun, refresh } = useWorkspace();
  const synthetic =
    !!context.data?.products.length &&
    context.data.products.every((product) => product.stock_code.startsWith('SYNTH-'));
  useEffect(() => {
    const change = () => {
      setRoute(window.location.hash.slice(2) || 'overview');
      setMobileOpen(false);
    };
    window.addEventListener('hashchange', change);
    return () => window.removeEventListener('hashchange', change);
  }, []);
  const page = pages.find((item) => item.id === route.split('?')[0]) || pages[0];
  const Page = page.component;
  return (
    <div className="app-shell">
      <a
        className="skip-link"
        href="#main-content"
        onClick={(event) => {
          event.preventDefault();
          document.getElementById('main-content')?.focus();
        }}
      >
        Skip to content
      </a>
      <aside className={`sidebar ${mobileOpen ? 'open' : ''}`} aria-label="Application sidebar">
        <a className="brand" href="#/overview" aria-label="DemandIQ overview">
          <span className="brand-symbol" aria-hidden="true">
            <i />
            <i />
            <i />
          </span>
          Demand<span>IQ</span>
        </a>
        <div className="workspace-label">RETAIL INTELLIGENCE</div>
        <nav aria-label="Main navigation">
          {pages.map(({ id, label, icon: Icon }) => (
            <a
              key={id}
              href={`#/${id}`}
              className={page.id === id ? 'active' : ''}
              aria-current={page.id === id ? 'page' : undefined}
            >
              <Icon size={18} strokeWidth={1.7} aria-hidden="true" />
              {label}
              {page.id === id && <span className="active-dot" />}
            </a>
          ))}
        </nav>
        <div className="sidebar-note">
          <Sparkles size={18} aria-hidden="true" />
          <h2>
            Better decisions.
            <br />
            Clearly explained.
          </h2>
          <p>Forecasts, assumptions and simulated outcomes, in one workspace.</p>
          <a href={`${API_BASE}/docs`} target="_blank" rel="noreferrer">
            Explore the API
            <ArrowRight size={14} aria-hidden="true" />
          </a>
        </div>
        <div className="sidebar-footer">
          <span className="status-dot" />
          Local decision support<span className="version">v1.0</span>
        </div>
      </aside>
      {mobileOpen && (
        <button
          className="mobile-scrim"
          aria-label="Close navigation"
          onClick={() => setMobileOpen(false)}
        />
      )}
      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            <button
              className="icon-button mobile-menu"
              aria-label={mobileOpen ? 'Close navigation' : 'Open navigation'}
              aria-expanded={mobileOpen}
              onClick={() => setMobileOpen(!mobileOpen)}
            >
              {mobileOpen ? <PanelLeftClose size={20} /> : <Menu size={20} />}
            </button>
            <span>Workspace</span>
            <span aria-hidden="true">/</span>
            <strong>{page.label}</strong>
          </div>
          <div className="topbar-actions">
            <span className="historical-label">
              <span className="status-dot" />
              {synthetic ? 'Synthetic demonstration data' : 'Historical retail data'}
            </span>
            <button
              className="icon-button refresh-button"
              onClick={refresh}
              aria-label="Refresh workspace"
            >
              <RefreshCw size={16} />
            </button>
            <button className="button primary compact" onClick={() => setSetupOpen(true)}>
              Activate data
              <ArrowRight size={15} aria-hidden="true" />
            </button>
          </div>
        </header>
        <div className="workspace-toolbar">
          <div className="workspace-picker">
            <label htmlFor="dataset-select">DATASET</label>
            <div className="select-wrap">
              <select
                id="dataset-select"
                value={context.data?.dataset?.dataset_id || ''}
                onChange={(event) => selectDataset(event.target.value)}
              >
                <option value="" disabled>
                  No dataset activated
                </option>
                {datasets.map((item) => (
                  <option key={item.dataset_id} value={item.dataset_id}>
                    {item.dataset_id.startsWith('3ec7b0') ? 'UCI Online Retail' : 'Retail dataset'}{' '}
                    · {shortId(item.dataset_id)}
                  </option>
                ))}
              </select>
              <ChevronDown size={13} aria-hidden="true" />
            </div>
          </div>
          <span className="toolbar-divider" />
          <div className="workspace-picker">
            <label htmlFor="run-select">FROZEN RUN</label>
            <div className="select-wrap">
              <select
                id="run-select"
                value={context.data?.run?.run_id || ''}
                onChange={(event) => selectRun(event.target.value)}
              >
                <option value="" disabled>
                  No run activated
                </option>
                {runs.map((item) => (
                  <option key={item.run_id} value={item.run_id}>
                    {shortId(item.run_id)}
                  </option>
                ))}
              </select>
              <ChevronDown size={13} aria-hidden="true" />
            </div>
          </div>
          <div className="toolbar-summary">
            {context.data?.products.length
              ? `${context.data.products.length} products · training-selected cohort`
              : 'Activate data to begin'}
          </div>
        </div>
        <main id="main-content" tabIndex={-1}>
          {synthetic && (
            <p className="note" role="note">
              Fictional synthetic data. These results demonstrate the workflow and are not evidence
              of real model performance or business savings.
            </p>
          )}
          {context.loading ? (
            <Loading />
          ) : context.error ? (
            <ErrorState error={context.error} retry={refresh} />
          ) : (
            <Suspense fallback={<Loading />}>
              <Page />
            </Suspense>
          )}
        </main>
        <footer className="main-footer">
          <span>DemandIQ · Forecast with context. Plan with confidence.</span>
          <span>Historical facts / predictions / assumptions / simulations</span>
        </footer>
      </div>
      <Activation open={setupOpen} close={() => setSetupOpen(false)} />
    </div>
  );
}
export default function App() {
  const [setupOpen, setSetupOpen] = useState(false);
  return (
    <WorkspaceProvider activate={() => setSetupOpen(true)}>
      <Shell setupOpen={setupOpen} setSetupOpen={setSetupOpen} />
    </WorkspaceProvider>
  );
}
