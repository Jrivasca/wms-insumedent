import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ChevronRight, RotateCcw } from 'lucide-react';
import { listPackingTasks } from '../api/packing';
import { errorMessage } from '../api/http';
import { Empty, ErrorBox, LoadingRows, PageHeader } from '../components/Async';
import DataTable, { MobileCardList, type Column } from '../components/DataTable';
import Pager from '../components/Pager';
import ProgressBar from '../components/ProgressBar';
import SearchInput from '../components/SearchInput';
import StatusBadge from '../components/StatusBadge';
import type { PackingTask } from '../types';

const PAGE = 50;

function progressOf(t: PackingTask): { packed: number; required: number } {
  return {
    required: t.lines.reduce((a, l) => a + l.quantity_required, 0),
    packed: t.lines.reduce((a, l) => a + l.quantity_packed, 0),
  };
}

export default function PackingPage() {
  const navigate = useNavigate();
  const [tasks, setTasks] = useState<PackingTask[]>([]);
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const [query, setQuery] = useState('');
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

  // El endpoint de packing no admite filtro de estado ni búsqueda: se filtra lo cargado.
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return tasks;
    return tasks.filter((t) =>
      [t.erp_order_number, t.order_id, t.assigned_to, t.id]
        .filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(q))
    );
  }, [tasks, query]);

  const columns: Column<PackingTask>[] = [
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
        const { packed, required } = progressOf(t);
        return <ProgressBar value={packed} total={required} unit="u" />;
      },
    },
    {
      key: 'packages',
      header: 'Bultos',
      align: 'right',
      render: (t) => t.packages.length,
    },
    {
      key: 'assigned',
      header: 'Responsable',
      secondary: true,
      render: (t) => <span className="text-slate-600">{t.assigned_to ?? 'Sin asignar'}</span>,
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
        title="Packing"
        subtitle="Todas las tareas de packing · abre una para continuarla"
        actions={
          <button onClick={() => load(offset)} className="btn-secondary">
            <RotateCcw className="h-4 w-4" aria-hidden="true" />
            Refrescar
          </button>
        }
      />

      <div className="mb-4 max-w-md">
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
          label={tasks.length === 0 ? 'No hay tareas de packing' : 'Ningún resultado'}
          hint={
            tasks.length === 0
              ? 'Las tareas se crean al completar el picking de un pedido.'
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
              onRowClick={(t) => navigate(`/my/packing/${t.id}`)}
            />
          </div>
          <div className="lg:hidden">
            <MobileCardList
              rows={shown}
              keyOf={(t) => t.id}
              render={(t) => {
                const { packed, required } = progressOf(t);
                return (
                  <button
                    type="button"
                    onClick={() => navigate(`/my/packing/${t.id}`)}
                    className="flex min-h-touch w-full items-center gap-3 text-left"
                  >
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-center gap-2">
                        <span className="code-strong">{t.erp_order_number ?? t.order_id}</span>
                        <StatusBadge status={t.status} />
                      </span>
                      <span className="mt-1 block text-xs text-slate-500">
                        {t.packages.length} bulto(s) · {t.lines.length} línea(s) ·{' '}
                        {t.assigned_to ?? 'sin asignar'}
                      </span>
                      <span className="mt-1 block">
                        <ProgressBar value={packed} total={required} unit="u" />
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
