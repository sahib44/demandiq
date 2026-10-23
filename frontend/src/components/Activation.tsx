import { useEffect, useRef, useState } from 'react';
import { Check, Database, ExternalLink, LoaderCircle, Play, X } from 'lucide-react';
import { API_BASE, submit, waitForJob } from '../api/client';
import type { Job, Json } from '../types/api';
import { useWorkspace } from './Workspace';
import { Note } from './UI';
import { shortId } from './format';

export const SAMPLE_DATASET = '3ec7b0b3e84f29eea43e501736bff880b7fc51aecde23ccadf9a9eae346ca90d';
export const SAMPLE_RUN = '6ad6f1a67c36a1304ba4aac1b9bf3052a1b5354d905ddf14f3cc99e7d777a6fa';

export function Activation({ open, close }: { open: boolean; close: () => void }) {
  const { refresh, context, selectWorkspace } = useWorkspace();
  const [source, setSource] = useState('existing');
  const [datasetId, setDatasetId] = useState(SAMPLE_DATASET);
  const [runId, setRunId] = useState(SAMPLE_RUN);
  const [file, setFile] = useState('');
  const [busy, setBusy] = useState(false);
  const [label, setLabel] = useState('');
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [done, setDone] = useState(false);
  const dialog = useRef<HTMLDivElement>(null);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    dialog.current?.querySelector<HTMLButtonElement>('button')?.focus();
    return () => previous?.focus();
  }, [open]);

  async function operation(
    path: string,
    payload: Record<string, Json>,
    description: string,
    signal: AbortSignal,
  ) {
    setLabel(description);
    return waitForJob(await submit(path, payload, signal), setJob, signal);
  }
  async function run(action: (signal: AbortSignal) => Promise<void>) {
    controller.current?.abort();
    controller.current = new AbortController();
    setBusy(true);
    setError(null);
    setDone(false);
    setJob(null);
    try {
      await action(controller.current.signal);
      setDone(true);
      refresh();
    } catch (error) {
      if (!controller.current.signal.aborted) setError(error as Error);
    } finally {
      setBusy(false);
    }
  }
  function sample() {
    void run(async (signal) => {
      const imported = await operation(
        '/datasets/import',
        { source: 'existing', dataset_id: SAMPLE_DATASET },
        '1 of 5 · Verifying historical dataset',
        signal,
      );
      const trained = await operation(
        '/training-runs',
        { dataset_id: SAMPLE_DATASET, mode: 'existing', run_id: SAMPLE_RUN },
        '2 of 5 · Loading frozen training run',
        signal,
      );
      await operation(
        '/forecasts',
        { run_id: SAMPLE_RUN, scope: 'one_week' },
        '3 of 5 · Generating historical one-week inference',
        signal,
      );
      const retrospective = await operation(
        '/forecasts',
        { run_id: SAMPLE_RUN, scope: 'retrospective' },
        '4 of 5 · Loading completed test predictions',
        signal,
      );
      const id = retrospective.result?.forecast_id;
      if (typeof id !== 'string')
        throw new Error('The completed job did not return a forecast reference.');
      await operation(
        '/inventory/scenarios',
        { forecast_id: id, config: {} },
        '5 of 5 · Loading retrospective inventory scenario',
        signal,
      );
      const dataset = imported.result?.dataset_id;
      const training = trained.result?.run_id;
      if (typeof dataset !== 'string' || typeof training !== 'string')
        throw new Error('The completed jobs did not return dataset and training references.');
      setDatasetId(dataset);
      setRunId(training);
      selectWorkspace(dataset, training);
    });
  }
  if (!open) return null;
  return (
    <div className="dialog-backdrop">
      <div
        className="activation-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="activation-title"
        ref={dialog}
        onKeyDown={(event) => {
          if (event.key === 'Escape') close();
          if (event.key === 'Tab') {
            const controls = dialog.current?.querySelectorAll<HTMLElement>(
              'button:not(:disabled),input:not(:disabled),select:not(:disabled),a[href]',
            );
            if (!controls?.length) return;
            const first = controls[0],
              last = controls[controls.length - 1];
            if (event.shiftKey && document.activeElement === first) {
              event.preventDefault();
              last.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
              event.preventDefault();
              first.focus();
            }
          }
        }}
      >
        <div className="dialog-heading">
          <div>
            <p className="eyebrow">Workspace setup</p>
            <h2 id="activation-title">Bring your data into focus.</h2>
          </div>
          <button className="icon-button" aria-label="Close workspace setup" onClick={close}>
            <X size={20} />
          </button>
        </div>
        <p>
          Imports and training run in the separate worker. Closing this panel does not cancel a
          submitted job.
        </p>
        <section className="sample-activation">
          <Database size={24} aria-hidden="true" />
          <div>
            <h3>Verified historical UCI sample</h3>
            <p>
              Activate existing local dataset and frozen models, generate historical inference, then
              load completed test and simulated inventory results. Requires the documented sample
              artifacts and evaluation ledger.
            </p>
            <button className="button primary" disabled={busy} onClick={sample}>
              <Play size={15} aria-hidden="true" />
              Activate historical sample
            </button>
          </div>
        </section>
        <Note>
          Sample forecasts refer to 2011, not today. Activation verifies completed evaluation
          artifacts; it never reevaluates the final forecasting test.
        </Note>
        <details className="setup-details">
          <summary>Import a dataset or load another run</summary>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void run(async (signal) => {
                const payload: Record<string, Json> = { source };
                if (source === 'existing') payload.dataset_id = datasetId;
                if (source === 'file') payload.input_file = file;
                const result = await operation(
                  '/datasets/import',
                  payload,
                  'Importing dataset',
                  signal,
                );
                const id = result.result?.dataset_id;
                if (typeof id !== 'string')
                  throw new Error('The completed job did not return a dataset reference.');
                setDatasetId(id);
                selectWorkspace(id);
              });
            }}
          >
            <label>
              Dataset source
              <select value={source} onChange={(event) => setSource(event.target.value)}>
                <option value="existing">Existing processed dataset</option>
                <option value="official">Download official UCI dataset</option>
                <option value="file">Local file under raw-data root</option>
              </select>
            </label>
            {source === 'existing' && (
              <label>
                Dataset ID
                <input
                  value={datasetId}
                  onChange={(event) => setDatasetId(event.target.value)}
                  pattern="[0-9a-f]{64}"
                  required
                />
              </label>
            )}
            {source === 'file' && (
              <label>
                Relative CSV or XLSX path
                <input
                  value={file}
                  onChange={(event) => setFile(event.target.value)}
                  placeholder="uci-online-retail/Online Retail.xlsx"
                  required
                />
              </label>
            )}
            <button className="button secondary" disabled={busy} type="submit">
              Import dataset
            </button>
          </form>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void run(async (signal) => {
                const trained = await operation(
                  '/training-runs',
                  { dataset_id: datasetId, mode: 'existing', run_id: runId },
                  'Loading frozen training run',
                  signal,
                );
                const id = trained.result?.run_id;
                if (typeof id !== 'string')
                  throw new Error('The completed job did not return a training reference.');
                selectWorkspace(datasetId, id);
              });
            }}
          >
            <label>
              Frozen run ID
              <input
                value={runId}
                onChange={(event) => setRunId(event.target.value)}
                pattern="[0-9a-f]{64}"
                required
              />
            </label>
            <button className="button secondary" disabled={busy} type="submit">
              Load frozen run
            </button>
          </form>
          {context.data?.run && (
            <div className="button-row">
              <button
                className="button secondary"
                disabled={busy}
                onClick={() =>
                  void run(async (signal) => {
                    await operation(
                      '/forecasts',
                      { run_id: context.data!.run!.run_id, scope: 'one_week' },
                      'Generating one-week inference',
                      signal,
                    );
                  })
                }
              >
                Generate one-week forecast
              </button>
              <button
                className="button secondary"
                disabled={busy}
                onClick={() =>
                  void run(async (signal) => {
                    await operation(
                      '/forecasts',
                      { run_id: context.data!.run!.run_id, scope: 'retrospective' },
                      'Loading completed test predictions',
                      signal,
                    );
                  })
                }
              >
                Load completed test
              </button>
            </div>
          )}
        </details>
        <div aria-live="polite" className="activation-status">
          {busy && (
            <>
              <LoaderCircle className="spin" size={18} aria-hidden="true" />
              <div>
                <strong>{label}</strong>
                {job && (
                  <p>
                    {job.status} · attempt {job.attempts} of {job.max_attempts} · job{' '}
                    {shortId(job.job_id)}
                  </p>
                )}
              </div>
            </>
          )}
          {done && (
            <>
              <Check size={20} aria-hidden="true" />
              <div>
                <strong>Workspace updated</strong>
                <p>Verified results are ready to explore.</p>
              </div>
            </>
          )}
          {error && (
            <p role="alert" className="inline-error">
              {error.message}
            </p>
          )}
        </div>
        <a className="text-link" href={`${API_BASE}/docs`} target="_blank" rel="noreferrer">
          API documentation
          <ExternalLink size={14} aria-hidden="true" />
        </a>
      </div>
    </div>
  );
}
