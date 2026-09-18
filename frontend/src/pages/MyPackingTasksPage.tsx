import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ChevronRight, RotateCcw } from 'lucide-react';
import { listPackingTasks } from '../api/packing';
import { errorMessage } from '../api/http';
import { Empty, ErrorBox, LoadingRows, PageHeader } from '../components/Async';
import ProgressBar from '../components/ProgressBar';
import StatusBadge from '../components/StatusBadge';
import type { PackingTask } from '../types';

export default function MyPackingTasksPage() {
  const [tasks, setTasks] = useState<PackingTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setTasks((await listPackingTasks({ assigned_to: 'me' })).items);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  return (
    <div>
      <PageHeader
        title="Mis tareas de packing"
        actions={
          <button onClick={load} className="btn-secondary">
            <RotateCcw className="h-4 w-4" aria-hidden="true" />
            Refrescar
          </button>
        }
      />

      {error && <ErrorBox message={error} onRetry={load} />}

      {loading ? (
        <LoadingRows rows={3} />
      ) : tasks.length === 0 ? (
        <Empty
          label="No tienes tareas de packing asignadas"
          hint="Cuando un pedido termine su picking, aparecerá acá."
        />
      ) : (
        <div className="space-y-3">
          {tasks.map((t) => {
            const required = t.lines.reduce((a, l) => a + l.quantity_required, 0);
            const packed = t.lines.reduce((a, l) => a + l.quantity_packed, 0);
            return (
              <Link
                key={t.id}
                to={`/my/packing/${t.id}`}
                className="card flex min-h-touch items-center gap-3 active:bg-slate-50"
              >
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="code-strong text-lg">{t.erp_order_number ?? t.order_id}</span>
                    <StatusBadge status={t.status} />
                  </span>
                  <span className="mt-0.5 block text-sm text-slate-500">
                    {t.lines.length} línea(s) · {t.packages.length} bulto(s)
                  </span>
                  <span className="mt-1 block">
                    <ProgressBar value={packed} total={required} unit="u" />
                  </span>
                </span>
                <ChevronRight className="h-6 w-6 shrink-0 text-slate-300" aria-hidden="true" />
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
