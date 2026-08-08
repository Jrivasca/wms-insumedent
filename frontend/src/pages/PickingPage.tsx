import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { listPickingTasks } from '../api/picking';
import { errorMessage } from '../api/http';
import { Empty, ErrorBox, Loading, PageHeader } from '../components/Async';
import Pager from '../components/Pager';
import StatusBadge from '../components/StatusBadge';
import type { PickingTask } from '../types';

const PAGE = 50;

export default function PickingPage() {
  const navigate = useNavigate();
  const [tasks, setTasks] = useState<PickingTask[]>([]);
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load(off = 0) {
    setLoading(true);
    setError(null);
    try {
      const data = await listPickingTasks({ status: status || undefined, limit: PAGE, offset: off });
      setTasks(data.items);
      setTotal(data.total);
      setOffset(off);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);

  return (
    <div>
      <PageHeader title="Picking" subtitle="Todas las tareas de picking · toca una tarea para abrirla o continuarla" />

      <div className="mb-4 flex items-end gap-2">
        <div>
          <label className="label">Estado</label>
          <select value={status} onChange={(e) => setStatus(e.target.value)} className="input">
            <option value="">Todos</option>
            <option value="pending">pending</option>
            <option value="in_progress">in_progress</option>
            <option value="completed">completed</option>
            <option value="partial">partial</option>
          </select>
        </div>
        <button onClick={() => load(offset)} className="btn-secondary">
          Refrescar
        </button>
      </div>

      {error && <ErrorBox message={error} onRetry={() => load(offset)} />}

      {loading ? (
        <Loading />
      ) : tasks.length === 0 ? (
        <Empty label="No hay tareas de picking" />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="table w-full">
            <thead className="bg-slate-50">
              <tr>
                <th>Tarea</th>
                <th>Pedido ERP</th>
                <th>Asignado a</th>
                <th>Líneas</th>
                <th>Progreso</th>
                <th>Estado</th>
                <th></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {tasks.map((t) => {
                const total = t.lines.reduce((a, l) => a + l.quantity_required, 0);
                const picked = t.lines.reduce((a, l) => a + l.quantity_picked, 0);
                return (
                  <tr
                    key={t.id}
                    onClick={() => navigate(`/my/picking/${t.id}`)}
                    className="cursor-pointer hover:bg-blue-50"
                  >
                    <td className="font-mono text-xs">{t.id}</td>
                    <td>{t.erp_order_number ?? t.order_id}</td>
                    <td>{t.assigned_to ?? '—'}</td>
                    <td>{t.lines.length}</td>
                    <td>
                      {picked}/{total}
                    </td>
                    <td>
                      <StatusBadge status={t.status} />
                    </td>
                    <td className="text-right font-semibold text-brand">Abrir ›</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <div className="mt-2">
        <Pager
          offset={offset}
          pageSize={PAGE}
          count={tasks.length}
          total={total}
          onPrev={() => load(Math.max(0, offset - PAGE))}
          onNext={() => load(offset + PAGE)}
        />
      </div>
    </div>
  );
}
