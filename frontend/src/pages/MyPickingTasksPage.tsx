import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { listPickingTasks } from '../api/picking';
import { errorMessage } from '../api/http';
import { Empty, ErrorBox, Loading, PageHeader } from '../components/Async';
import StatusBadge from '../components/StatusBadge';
import type { PickingTask } from '../types';

export default function MyPickingTasksPage() {
  const [tasks, setTasks] = useState<PickingTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setTasks(await listPickingTasks({ assigned_to: 'me' }));
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
        title="Mis tareas de picking"
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
        <Empty label="No tienes tareas de picking asignadas" />
      ) : (
        <div className="space-y-3">
          {tasks.map((t) => {
            const total = t.lines.reduce((a, l) => a + l.quantity_required, 0);
            const picked = t.lines.reduce((a, l) => a + l.quantity_picked, 0);
            return (
              <Link
                key={t.id}
                to={`/my/picking/${t.id}`}
                className="card flex items-center justify-between active:bg-slate-50"
              >
                <div>
                  <div className="text-lg font-bold">{t.erp_order_number ?? t.order_id}</div>
                  <div className="text-sm text-slate-500">
                    {t.lines.length} líneas · {picked}/{total} unidades
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
