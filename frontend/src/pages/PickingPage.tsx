import { useEffect, useState } from 'react';
import { listPickingTasks } from '../api/picking';
import { errorMessage } from '../api/http';
import { Empty, ErrorBox, Loading, PageHeader } from '../components/Async';
import StatusBadge from '../components/StatusBadge';
import type { PickingTask } from '../types';

export default function PickingPage() {
  const [tasks, setTasks] = useState<PickingTask[]>([]);
  const [status, setStatus] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setTasks(await listPickingTasks({ status: status || undefined }));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);

  return (
    <div>
      <PageHeader title="Picking" subtitle="Todas las tareas de picking" />

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
        <button onClick={load} className="btn-secondary">
          Refrescar
        </button>
      </div>

      {error && <ErrorBox message={error} onRetry={load} />}

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
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {tasks.map((t) => {
                const total = t.lines.reduce((a, l) => a + l.quantity_required, 0);
                const picked = t.lines.reduce((a, l) => a + l.quantity_picked, 0);
                return (
                  <tr key={t.id}>
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
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
