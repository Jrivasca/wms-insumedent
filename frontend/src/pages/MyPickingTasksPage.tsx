import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowRight, ChevronRight, PackagePlus, RotateCcw } from 'lucide-react';
import { listPickingTasks } from '../api/picking';
import { listCompletableOrders, resumePartialOrder } from '../api/orders';
import { errorMessage } from '../api/http';
import { Empty, ErrorBox, LoadingRows, PageHeader } from '../components/Async';
import ProgressBar from '../components/ProgressBar';
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
            <RotateCcw className="h-4 w-4" aria-hidden="true" />
            Refrescar
          </button>
        }
      />

      {error && <ErrorBox message={error} onRetry={load} />}

      {loading ? (
        <LoadingRows rows={3} />
      ) : (
        <>
          {/* Llegó stock para pedidos que habían quedado cortos: se pueden completar. */}
          {completable.length > 0 && (
            <section className="mb-6">
              <h2 className="mb-2 flex items-center gap-1.5 text-sm font-semibold uppercase tracking-wide text-emerald-700">
                <PackagePlus className="h-4 w-4" aria-hidden="true" />
                Llegó stock · listos para completar
              </h2>
              <div className="space-y-3">
                {completable.map((o) => (
                  <div key={o.order_id} className="card border-l-4 border-l-emerald-500">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <span className="code-strong text-lg">{o.erp_order_number}</span>
                        {o.customer && (
                          <p className="truncate text-sm text-slate-500">{o.customer}</p>
                        )}
                      </div>
                      <StatusBadge status={o.status} />
                    </div>
                    <ul className="mt-3 space-y-1 text-sm">
                      {o.lines.map((l) => (
                        <li key={l.line_id} className="flex justify-between gap-2">
                          <span className="min-w-0 truncate">
                            <span className="code">{l.sku}</span> {l.name}
                          </span>
                          <span className="shrink-0 font-semibold tabular-nums text-emerald-700">
                            faltan {l.missing}
                          </span>
                        </li>
                      ))}
                    </ul>
                    <button
                      onClick={() => handleResume(o.order_id)}
                      className="btn-xl mt-3 w-full bg-emerald-600 text-white hover:bg-emerald-700"
                      disabled={resuming !== null}
                    >
                      {resuming === o.order_id ? 'Retomando…' : 'Completar faltante'}
                      {resuming !== o.order_id && (
                        <ArrowRight className="h-5 w-5" aria-hidden="true" />
                      )}
                    </button>
                  </div>
                ))}
              </div>
            </section>
          )}

          {tasks.length === 0 ? (
            completable.length === 0 && (
              <Empty
                label="No tienes tareas de picking asignadas"
                hint="Cuando te asignen un pedido, aparecerá acá."
              />
            )
          ) : (
            <div className="space-y-3">
              {tasks.map((t) => {
                const required = t.lines.reduce((a, l) => a + l.quantity_required, 0);
                const picked = t.lines.reduce((a, l) => a + l.quantity_picked, 0);
                return (
                  <Link
                    key={t.id}
                    to={`/my/picking/${t.id}`}
                    className="card flex min-h-touch items-center gap-3 active:bg-slate-50"
                  >
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-center gap-2">
                        <span className="code-strong text-lg">
                          {t.erp_order_number ?? t.order_id}
                        </span>
                        <StatusBadge status={t.status} />
                      </span>
                      <span className="mt-0.5 block text-sm text-slate-500">
                        {t.lines.length} línea(s)
                      </span>
                      <span className="mt-1 block">
                        <ProgressBar value={picked} total={required} unit="u" />
                      </span>
                    </span>
                    <ChevronRight className="h-6 w-6 shrink-0 text-slate-300" aria-hidden="true" />
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
