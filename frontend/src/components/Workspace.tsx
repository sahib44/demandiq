import { createContext, useCallback, useContext, useState, type ReactNode } from 'react';
import { query } from '../api/client';
import { useResource, type Resource } from '../hooks/useResource';
import type { Dataset, TrainingRun, WorkspaceContext } from '../types/api';

interface WorkspaceValue {
  context: Resource<WorkspaceContext>;
  datasets: Dataset[];
  runs: TrainingRun[];
  revision: number;
  refresh: () => void;
  selectDataset: (id: string) => void;
  selectRun: (id: string) => void;
  selectWorkspace: (datasetId: string, runId?: string) => void;
  activate: () => void;
}
const Workspace = createContext<WorkspaceValue | null>(null);
export function WorkspaceProvider({
  children,
  activate,
}: {
  children: ReactNode;
  activate: () => void;
}) {
  const [datasetId, setDatasetId] = useState('');
  const [runId, setRunId] = useState('');
  const [revision, setRevision] = useState(0);
  const refresh = useCallback(() => setRevision((value) => value + 1), []);
  const selectWorkspace = useCallback((dataset: string, run = '') => {
    setDatasetId(dataset);
    setRunId(run);
  }, []);
  const context = useResource<WorkspaceContext>(
    query('/dashboard/context', { dataset_id: datasetId, run_id: runId }),
    revision,
  );
  const datasets = useResource<Dataset[]>('/datasets?limit=200', revision);
  const activeDataset = datasetId || context.data?.dataset?.dataset_id;
  const runs = useResource<TrainingRun[]>(
    activeDataset ? query('/training-runs', { dataset_id: activeDataset, limit: '200' }) : null,
    revision,
  );
  return (
    <Workspace.Provider
      value={{
        context,
        datasets: datasets.data || [],
        runs: runs.data || [],
        revision,
        refresh,
        selectDataset: (id) => {
          setDatasetId(id);
          setRunId('');
        },
        selectRun: setRunId,
        selectWorkspace,
        activate,
      }}
    >
      {children}
    </Workspace.Provider>
  );
}
export function useWorkspace() {
  const value = useContext(Workspace);
  if (!value) throw new Error('WorkspaceProvider is required');
  return value;
}
