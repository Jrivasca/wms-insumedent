import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { listPackingTasks } from '../api/packing';
import { errorMessage } from '../api/http';
import { Empty, ErrorBox, Loading, PageHeader } from '../components/Async';
import Pager from '../components/Pager';
import StatusBadge from '../components/StatusBadge';
import type { PackingTask } from '../types';

const PAGE = 50;

export default function PackingPage() {
  const navigate = useNavigate();
  const [tasks, setTasks] = useState<PackingTask[]>([]);
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load(off = 0) {
    setLoading(true);
    setError(null);
    try {
      const data = await listPackingTasks({ limit: PAGE, offset: off });
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
  }, []);

  return (
    <div>
      <PageHeader
        title="Packing"
        subtitle="Todas las tareas de packing · toca una tarea para abrirla o continuarla"
        actions={
          <button onClick={() => load(offset)} className="btn-secondary">
            Refrescar
          </button>
        }
      />

      {error && <ErrorBox message={error} onRetry={() => load(offset)} />}

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
                <th></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {tasks.map((t) => {
                const total = t.lines.reduce((a, l) => a + l.quantity_required, 0);
                const packed = t.lines.reduce((a, l) => a + l.quantity_packed, 0);
                return (
                  <tr
                    key={t.id}
                    onClick={() => navigate(`/my/packing/${t.id}`)}
                    className="cursor-pointer hover:bg-blue-50"
                  >
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
