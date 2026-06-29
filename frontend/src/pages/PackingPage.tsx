import { useEffect, useState } from 'react';
import { listPackingTasks } from '../api/packing';
import { errorMessage } from '../api/http';
import { Empty, ErrorBox, Loading, PageHeader } from '../components/Async';
import StatusBadge from '../components/StatusBadge';
import type { PackingTask } from '../types';

export default function PackingPage() {
  const [tasks, setTasks] = useState<PackingTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setTasks(await listPackingTasks());
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
        title="Packing"
        subtitle="Todas las tareas de packing"
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
        <Empty label="No hay tareas de packing" />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="table w-full">
            <thead className="bg-slate-50">
              <tr>
                <th>Tarea</th>
                <th>Pedido</th>
                <th>Asignado a</th>
                <th>Bultos</th>
                <th>Líneas</th>
                <th>Progreso</th>
                <th>Estado</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {tasks.map((t) => {
                const total = t.lines.reduce((a, l) => a + l.quantity_required, 0);
                const packed = t.lines.reduce((a, l) => a + l.quantity_packed, 0);
                return (
                  <tr key={t.id}>
                    <td className="font-mono text-xs">{t.id}</td>
                    <td>{t.order_id}</td>
                    <td>{t.assigned_to ?? '—'}</td>
                    <td>{t.packages.length}</td>
                    <td>{t.lines.length}</td>
                    <td>
                      {packed}/{total}
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
