import { useEffect, useState } from 'react';
import { cancelSyncJob, listSyncJobs, retrySyncJob } from '../api/syncJobs';
import { errorMessage } from '../api/http';
import { Empty, ErrorBox, Loading, PageHeader } from '../components/Async';
import StatusBadge from '../components/StatusBadge';
import type { SyncJob } from '../types';

export default function SyncJobsPage() {
  const [jobs, setJobs] = useState<SyncJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setJobs(await listSyncJobs());
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function handleRetry(id: string) {
    setBusy(id);
    try {
      await retrySyncJob(id);
      load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function handleCancel(id: string) {
    setBusy(id);
    try {
      await cancelSyncJob(id);
      load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  const canRetry = (s: string) => s === 'failed' || s === 'error' || s === 'retrying';
  const canCancel = (s: string) =>
    s === 'pending' || s === 'queued' || s === 'retrying' || s === 'running';

  return (
    <div>
      <PageHeader
        title="Cola de Sincronización"
        subtitle="Trabajos de sincronización con ERP"
        actions={
          <button onClick={load} className="btn-secondary">
            Refrescar
          </button>
        }
      />

      {error && <ErrorBox message={error} onRetry={load} />}

      {loading ? (
        <Loading />
      ) : jobs.length === 0 ? (
        <Empty label="No hay trabajos de sincronización" />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="table w-full">
            <thead className="bg-slate-50">
              <tr>
                <th>ID</th>
                <th>ERP</th>
                <th>Tipo</th>
                <th>Estado</th>
                <th>Intentos</th>
                <th>Próx. reintento</th>
                <th>Último error</th>
                <th></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {jobs.map((j) => (
                <tr key={j.id} className="align-top">
                  <td className="font-mono text-xs">{j.id}</td>
                  <td>{j.erp}</td>
                  <td>{j.job_type}</td>
                  <td>
                    <StatusBadge status={j.status} />
                  </td>
                  <td>
                    {j.attempts}/{j.max_attempts}
                  </td>
                  <td className="text-xs text-slate-500">
                    {j.next_retry_at ? new Date(j.next_retry_at).toLocaleString() : '—'}
                  </td>
                  <td className="max-w-xs text-xs text-red-600">{j.last_error ?? '—'}</td>
                  <td>
                    <div className="flex gap-2">
                      <button
                        onClick={() => handleRetry(j.id)}
                        className="btn-secondary"
                        disabled={busy === j.id || !canRetry(j.status)}
                      >
                        Reintentar
                      </button>
                      <button
                        onClick={() => handleCancel(j.id)}
                        className="btn-danger"
                        disabled={busy === j.id || !canCancel(j.status)}
                      >
                        Cancelar
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
