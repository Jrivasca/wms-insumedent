import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ChevronRight, RotateCcw } from 'lucide-react';
import { listPickingTasks } from '../api/picking';
import { listUsers } from '../api/users';
import { errorMessage } from '../api/http';
import { Empty, ErrorBox, LoadingRows, PageHeader } from '../components/Async';
import DataTable, { MobileCardList, type Column } from '../components/DataTable';
import Pager from '../components/Pager';
import ProgressBar from '../components/ProgressBar';
import SearchInput from '../components/SearchInput';
import StatusBadge from '../components/StatusBadge';
import { statusLabel } from '../lib/status';
import type { PickingTask } from '../types';

const PAGE = 50;

/** Estados que acepta el backend para filtrar; el valor no cambia, solo la etiqueta. */
const STATUSES = [
  'pending',
  'in_progress',
  'paused',
  'completed',
  'completed_with_differences',
  'cancelled',
];

function progressOf(t: PickingTask): { picked: number; required: number } {
  return {
    required: t.lines.reduce((a, l) => a + l.quantity_required, 0),
    picked: t.lines.reduce((a, l) => a + l.quantity_picked, 0),
  };
}

export default function PickingPage() {
  const navigate = useNavigate();
  const [tasks, setTasks] = useState<PickingTask[]>([]);
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState('');
  const [query, setQuery] = useState('');
  const [userNames, setUserNames] = useState<Record<string, string>>({});
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

  // Las tareas traen el id del usuario asignado; acá se muestra su nombre.
  useEffect(() => {
    listUsers()
      .then((us) => {
        const map: Record<string, string> = {};
        for (const u of us) map[u.id] = u.name;
        setUserNames(map);
      })
      .catch(() => undefined); // sin nombres se muestra el id, no se rompe la pantalla
  }, []);

  function assignedName(id?: string): string {
    if (!id) return 'Sin asignar';
    return userNames[id] ?? id;
  }

  // El backend no busca por texto en tareas: este filtro actúa sobre las filas cargadas.
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return tasks;
    return tasks.filter((t) =>
      [t.erp_order_number, t.order_id, t.assigned_to, assignedName(t.assigned_to), t.id]
        .filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(q))
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tasks, query, userNames]);

  const columns: Column<PickingTask>[] = [
    {
      key: 'order',
      header: 'Pedido',
      render: (t) => <span className="code-strong">{t.erp_order_number ?? t.order_id}</span>,
    },
    {
      key: 'status',
      header: 'Estado',
      render: (t) => <StatusBadge status={t.status} />,
    },
    {
      key: 'progress',
      header: 'Avance',
      width: '11rem',
      render: (t) => {
        const { picked, required } = progressOf(t);
        return <ProgressBar value={picked} total={required} unit="u" />;
      },
    },
    {
      key: 'assigned',
      header: 'Responsable',
      secondary: true,
      render: (t) => <span className="text-slate-600">{assignedName(t.assigned_to)}</span>,
    },
    {
      key: 'lines',
      header: 'Líneas',
      align: 'right',
      secondary: true,
      render: (t) => t.lines.length,
    },
    {
      key: 'go',
      header: '',
      align: 'right',
      width: '3rem',
      render: () => <ChevronRight className="inline h-4 w-4 text-slate-400" aria-hidden="true" />,
    },
  ];

  return (
    <div>
      <PageHeader
        title="Picking"
        subtitle="Todas las tareas de picking · abre una para continuarla"
        actions={
          <button onClick={() => load(offset)} className="btn-secondary">
            <RotateCcw className="h-4 w-4" aria-hidden="true" />
            Refrescar
          </button>
        }
      />

      <div className="mb-4 grid gap-2 sm:grid-cols-[14rem_1fr]">
        <div>
          <label className="label" htmlFor="picking-status">
            Estado
          </label>
          <select
            id="picking-status"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            className="input"
          >
            <option value="">Todos los estados</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {statusLabel(s)}
              </option>
            ))}
          </select>
        </div>
        <SearchInput
          label="Buscar"
          value={query}
          onChange={setQuery}
          placeholder="N° de pedido o responsable…"
        />
      </div>

      {error && <ErrorBox message={error} onRetry={() => load(offset)} />}

      {loading ? (
        <LoadingRows />
      ) : shown.length === 0 ? (
        <Empty
          label={tasks.length === 0 ? 'No hay tareas de picking' : 'Ningún resultado'}
          hint={
            tasks.length === 0
              ? 'Las tareas se crean al generar el picking de un pedido.'
              : 'El filtro se aplica a las tareas ya cargadas en esta página.'
          }
        />
      ) : (
        <>
          <div className="hidden lg:block">
            <DataTable
              columns={columns}
              rows={shown}
              keyOf={(t) => t.id}
              onRowClick={(t) => navigate(`/my/picking/${t.id}`)}
            />
          </div>
          <div className="lg:hidden">
            <MobileCardList
              rows={shown}
              keyOf={(t) => t.id}
              render={(t) => {
                const { picked, required } = progressOf(t);
                return (
                  <button
                    type="button"
                    onClick={() => navigate(`/my/picking/${t.id}`)}
                    className="flex min-h-touch w-full items-center gap-3 text-left"
                  >
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-center gap-2">
                        <span className="code-strong">{t.erp_order_number ?? t.order_id}</span>
                        <StatusBadge status={t.status} />
                      </span>
                      <span className="mt-1 block text-xs text-slate-500">
                        {t.lines.length} línea(s) · {assignedName(t.assigned_to)}
                      </span>
                      <span className="mt-1 block">
                        <ProgressBar value={picked} total={required} unit="u" />
                      </span>
                    </span>
                    <ChevronRight className="h-5 w-5 shrink-0 text-slate-400" aria-hidden="true" />
                  </button>
                );
              }}
            />
          </div>
        </>
      )}

      {query.trim() !== '' && shown.length > 0 && (
        <p className="hint mt-2">
          Se muestran {shown.length} de las {tasks.length} tareas cargadas en esta página.
        </p>
      )}

      <div className="mt-3">
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
