import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { listPickingTasks } from '../api/picking';
import { listCompletableOrders, resumePartialOrder } from '../api/orders';
import { errorMessage } from '../api/http';
import { Empty, ErrorBox, Loading, PageHeader } from '../components/Async';
import StatusBadge from '../components/StatusBadge';
import type { CompletableOrder, PickingTask } from '../types';

export default function MyPickingTasksPage() {
  const navigate = useNavigate();
  const [tasks, setTasks] = useState<PickingTask[]>([]);
  const [completable, setCompletable] = useState<CompletableOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [resuming, setResuming] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [mine, ready] = await Promise.all([
        listPickingTasks({ assigned_to: 'me' }),
        // La lista de "listos para completar" no debe bloquear las tareas propias.
        listCompletableOrders().catch(() => [] as CompletableOrder[]),
      ]);
      setTasks(mine.items);
      setCompletable(ready);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function handleResume(orderId: string) {
    setResuming(orderId);
    setError(null);
    try {
      const task = await resumePartialOrder(orderId);
      navigate(`/my/picking/${task.id}`);
    } catch (err) {
      setError(errorMessage(err));
      setResuming(null);
      load();
    }
  }

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
      ) : (
        <>
          {completable.length > 0 && (
            <section className="mb-6">
              <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-emerald-700">
                📥 Llegó stock · listos para completar
              </h2>
              <div className="space-y-3">
                {completable.map((o) => (
                  <div key={o.order_id} className="card border-l-4 border-emerald-500">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="text-lg font-bold">{o.erp_order_number}</div>
                        {o.customer && (
                          <div className="truncate text-sm text-slate-500">{o.customer}</div>
                        )}
                      </div>
                      <StatusBadge status={o.status} />
                    </div>
                    <ul className="mt-2 space-y-1 text-sm">
                      {o.lines.map((l) => (
                        <li key={l.line_id} className="flex justify-between gap-2">
                          <span className="min-w-0 truncate">
                            <span className="font-mono text-xs text-slate-500">{l.sku}</span>{' '}
                            {l.name}
                          </span>
                          <span className="shrink-0 font-medium text-emerald-700">
                            faltan {l.missing}
                          </span>
                        </li>
                      ))}
                    </ul>
                    <button
                      onClick={() => handleResume(o.order_id)}
                      className="btn-xl mt-3 w-full bg-emerald-600 text-white"
                      disabled={resuming !== null}
                    >
                      {resuming === o.order_id ? 'Retomando…' : 'Completar faltante →'}
                    </button>
                  </div>
                ))}
              </div>
            </section>
          )}

          {tasks.length === 0 ? (
            completable.length === 0 && <Empty label="No tienes tareas de picking asignadas" />
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
        </>
      )}
    </div>
  );
}
