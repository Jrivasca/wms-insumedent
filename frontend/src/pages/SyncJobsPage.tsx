import { useEffect, useState } from 'react';
import { AlertTriangle, Ban, RefreshCw, RotateCcw } from 'lucide-react';
import { cancelSyncJob, listSyncJobs, retrySyncJob } from '../api/syncJobs';
import { errorMessage } from '../api/http';
import { Empty, ErrorBox, LoadingRows, PageHeader } from '../components/Async';
import ConfirmDialog from '../components/ConfirmDialog';
import DataTable, { MobileCardList, type Column } from '../components/DataTable';
import StatusBadge from '../components/StatusBadge';
import type { SyncJob } from '../types';

/** Tipos de trabajo del backend (SyncJobType), dichos en términos de la operación. */
const JOB_LABELS: Record<string, string> = {
  sync_products: 'Traer productos',
  sync_orders: 'Traer pedidos',
  create_inventory_document: 'Enviar movimiento de inventario',
  dispatch_order: 'Despachar pedido en el ERP',
  create_product: 'Crear producto en el ERP',
  create_order: 'Crear pedido en el ERP',
};

function jobLabel(type: string): string {
  return JOB_LABELS[type] ?? type;
}

// Estados reales de SyncJobStatus: pending, processing, success, failed, retrying, cancelled.
const canRetry = (s: string) => s === 'failed' || s === 'retrying';
const canCancel = (s: string) => s === 'pending' || s === 'processing' || s === 'retrying';

function fechaHora(iso?: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString('es-CL');
}

export default function SyncJobsPage() {
  const [jobs, setJobs] = useState<SyncJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [toCancel, setToCancel] = useState<SyncJob | null>(null);

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
    setError(null);
    try {
      await retrySyncJob(id);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function handleCancel() {
    if (!toCancel) return;
    setBusy(toCancel.id);
    setError(null);
    try {
      await cancelSyncJob(toCancel.id);
      setToCancel(null);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  const failed = jobs.filter((j) => j.status === 'failed').length;

  const columns: Column<SyncJob>[] = [
    {
      key: 'job',
      header: 'Trabajo',
      render: (j) => (
        <span>
          <span className="block font-medium text-slate-900">{jobLabel(j.job_type)}</span>
          <span className="code">{j.id}</span>
        </span>
      ),
    },
    {
      key: 'status',
      header: 'Estado',
      render: (j) => <StatusBadge status={j.status} />,
    },
    {
      key: 'attempts',
      header: 'Intentos',
      align: 'right',
      render: (j) => (
        <span className="tabular-nums">
          {j.attempts} de {j.max_attempts}
        </span>
      ),
    },
    {
      key: 'next',
      header: 'Próximo reintento',
      secondary: true,
      render: (j) => (
        <span className="whitespace-nowrap text-xs text-slate-500">{fechaHora(j.next_retry_at)}</span>
      ),
    },
    {
      key: 'error',
      header: 'Último error',
      secondary: true,
      render: (j) =>
        j.last_error ? (
          <span className="block max-w-xs break-words text-xs text-red-700" title={j.last_error}>
            {j.last_error}
          </span>
        ) : (
          <span className="text-xs text-slate-400">—</span>
        ),
    },
    {
      key: 'actions',
      header: '',
      align: 'right',
      render: (j) => (
        <div className="flex justify-end gap-2">
          <button
            onClick={() => handleRetry(j.id)}
            className="btn-secondary btn-sm"
            disabled={busy === j.id || !canRetry(j.status)}
          >
            <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
            Reintentar
          </button>
          <button
            onClick={() => setToCancel(j)}
            className="btn-secondary btn-sm text-red-700"
            disabled={busy === j.id || !canCancel(j.status)}
          >
            <Ban className="h-3.5 w-3.5" aria-hidden="true" />
            Cancelar
          </button>
        </div>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="Cola de sincronización"
        subtitle="Todo lo que el WMS le envía a Defontana pasa por acá"
        actions={
          <button onClick={load} className="btn-secondary">
            <RotateCcw className="h-4 w-4" aria-hidden="true" />
            Refrescar
          </button>
        }
      />

      {error && <ErrorBox message={error} onRetry={load} />}

      {failed > 0 && (
        <div className="mb-4 flex items-start gap-2 rounded-card border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <span>
            {failed} trabajo(s) agotaron sus reintentos y no llegaron a Defontana. Revisa el error y
            reintenta cuando esté resuelto.
          </span>
        </div>
      )}

      {loading ? (
        <LoadingRows />
      ) : jobs.length === 0 ? (
        <Empty
          label="No hay trabajos en la cola"
          hint="Aquí aparecen las recepciones, ajustes y despachos mientras viajan al ERP."
        />
      ) : (
        <>
          <div className="hidden lg:block">
            <DataTable columns={columns} rows={jobs} keyOf={(j) => j.id} />
          </div>
          <div className="lg:hidden">
            <MobileCardList
              rows={jobs}
              keyOf={(j) => j.id}
              render={(j) => (
                <div>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-medium text-slate-900">{jobLabel(j.job_type)}</span>
                    <StatusBadge status={j.status} />
                  </div>
                  <p className="mt-1 text-xs text-slate-500">
                    Intento {j.attempts} de {j.max_attempts}
                    {j.next_retry_at && <> · próximo {fechaHora(j.next_retry_at)}</>}
                  </p>
                  {j.last_error && (
                    <p className="mt-1 break-words text-xs text-red-700">{j.last_error}</p>
                  )}
                  <div className="mt-2 flex gap-2">
                    <button
                      onClick={() => handleRetry(j.id)}
                      className="btn-secondary btn-sm"
                      disabled={busy === j.id || !canRetry(j.status)}
                    >
                      <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
                      Reintentar
                    </button>
                    <button
                      onClick={() => setToCancel(j)}
                      className="btn-secondary btn-sm text-red-700"
                      disabled={busy === j.id || !canCancel(j.status)}
                    >
                      <Ban className="h-3.5 w-3.5" aria-hidden="true" />
                      Cancelar
                    </button>
                  </div>
                </div>
              )}
            />
          </div>
        </>
      )}

      <ConfirmDialog
        open={toCancel !== null}
        title="¿Cancelar este envío al ERP?"
        message={
          toCancel
            ? `«${jobLabel(toCancel.job_type)}» no se volverá a intentar, así que ese dato no llegará a Defontana y tendrás que repetir la operación en el WMS.`
            : ''
        }
        confirmLabel="Cancelar el envío"
        cancelLabel="Volver"
        busy={busy !== null}
        onConfirm={handleCancel}
        onCancel={() => setToCancel(null)}
      />
    </div>
  );
}
