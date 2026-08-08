import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { listPackingTasks } from '../api/packing';
import { errorMessage } from '../api/http';
import { Empty, ErrorBox, Loading, PageHeader } from '../components/Async';
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
            Refrescar
          </button>
        }
      />

      {error && <ErrorBox message={error} onRetry={load} />}

      {loading ? (
        <Loading />
      ) : tasks.length === 0 ? (
        <Empty label="No tienes tareas de packing asignadas" />
      ) : (
        <div className="space-y-3">
          {tasks.map((t) => {
            const total = t.lines.reduce((a, l) => a + l.quantity_required, 0);
            const packed = t.lines.reduce((a, l) => a + l.quantity_packed, 0);
            return (
              <Link
                key={t.id}
                to={`/my/packing/${t.id}`}
                className="card flex items-center justify-between active:bg-slate-50"
              >
                <div>
                  <div className="text-lg font-bold">Pedido {t.order_id}</div>
                  <div className="text-sm text-slate-500">
                    {t.lines.length} líneas · {packed}/{total} unidades · {t.packages.length} bultos
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <StatusBadge status={t.status} />
                  <span className="text-2xl text-slate-300">›</span>
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
