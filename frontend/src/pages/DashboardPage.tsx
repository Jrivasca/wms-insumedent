import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import type { ComponentType } from 'react';
import {
  AlertTriangle,
  Boxes,
  CheckCheck,
  ChevronRight,
  CircleAlert,
  ClipboardList,
  MapPin,
  Package,
  PackageCheck,
  PackageSearch,
  PackageX,
  PlugZap,
  RefreshCw,
  RotateCcw,
  Truck,
} from 'lucide-react';
import { getDashboardStats } from '../api/dashboard';
import { getDefontanaStatus } from '../api/integrations';
import { ErrorBox, Loading, PageHeader } from '../components/Async';
import MetricCard from '../components/MetricCard';
import StatusBadge from '../components/StatusBadge';
import { errorMessage } from '../api/http';
import type { DashboardStats, DefontanaStatus } from '../types';

interface Attention {
  id: string;
  tone: 'danger' | 'warn';
  count: number;
  label: string;
  hint: string;
  to: string;
  Icon: ComponentType<{ className?: string }>;
}

const TONE_ROW: Record<'danger' | 'warn', { icon: string; count: string }> = {
  danger: { icon: 'bg-red-100 text-red-700', count: 'text-red-800' },
  warn: { icon: 'bg-amber-100 text-amber-700', count: 'text-amber-900' },
};

/**
 * Lo que necesita atención, en orden de urgencia y solo con datos reales: cada fila
 * aparece únicamente si su contador es mayor que cero y lleva a la pantalla donde
 * se resuelve.
 */
function buildAttention(stats: DashboardStats, defontana: DefontanaStatus | null): Attention[] {
  const { orders: o, inventory: inv, operations: op } = stats;
  const rows: Attention[] = [];

  if (o.error_cancelados > 0) {
    rows.push({
      id: 'error',
      tone: 'danger',
      count: o.error_cancelados,
      label: 'Pedidos cancelados o con error de sincronización',
      hint: 'Revisar antes de seguir operándolos',
      to: '/orders',
      Icon: CircleAlert,
    });
  }
  if (defontana && defontana.status !== 'connected') {
    rows.push({
      id: 'erp',
      tone: 'danger',
      count: 1,
      label: 'La conexión con Defontana no está operativa',
      hint: 'Sin ella no viajan recepciones, ajustes ni pedidos',
      to: '/settings/defontana',
      Icon: PlugZap,
    });
  }
  if (op.sync_pendientes > 0) {
    rows.push({
      id: 'sync',
      tone: 'warn',
      count: op.sync_pendientes,
      label: 'Envíos al ERP en cola',
      hint: 'Se reintentan solos; si no bajan, hay algo detenido',
      to: '/sync-jobs',
      Icon: RefreshCw,
    });
  }
  if (o.parciales > 0) {
    rows.push({
      id: 'parciales',
      tone: 'warn',
      count: o.parciales,
      label: 'Pedidos con faltante de stock',
      hint: 'Quedaron cortos al pickear',
      to: '/orders',
      Icon: PackageX,
    });
  }
  if (o.despacho_parcial > 0) {
    rows.push({
      id: 'despacho-parcial',
      tone: 'warn',
      count: o.despacho_parcial,
      label: 'Pedidos despachados en parte',
      hint: 'Falta completar el despacho',
      to: '/dispatch',
      Icon: Truck,
    });
  }
  if (inv.sin_stock > 0) {
    rows.push({
      id: 'sin-stock',
      tone: 'warn',
      count: inv.sin_stock,
      label: 'Productos sin stock',
      hint: 'No se pueden comprometer en pedidos nuevos',
      to: '/inventory',
      Icon: PackageX,
    });
  }
  return rows;
}

function fechaHora(iso?: string | null): string {
  if (!iso) return 'nunca';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? 'nunca' : d.toLocaleString('es-CL');
}

export default function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [defontana, setDefontana] = useState<DefontanaStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [s, d] = await Promise.all([
        getDashboardStats(),
        getDefontanaStatus().catch(() => null),
      ]);
      setStats(s);
      setDefontana(d);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  if (loading) return <Loading />;
  if (error) return <ErrorBox message={error} onRetry={load} />;
  if (!stats) return null;

  const { orders: o, inventory: inv, operations: op } = stats;
  const attention = buildAttention(stats, defontana);
  const estados = Object.entries(o.por_estado).filter(([, n]) => n > 0);

  return (
    <div>
      <PageHeader
        title="Resumen"
        subtitle="Estado de la operación de hoy"
        actions={
          <button onClick={load} className="btn-secondary">
            <RotateCcw className="h-4 w-4" aria-hidden="true" />
            Refrescar
          </button>
        }
      />

      {/* 1. Lo que necesita atención */}
      <section className="mb-6">
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
          La operación necesita tu atención
        </h2>
        {attention.length === 0 ? (
          <div className="flex items-center gap-3 rounded-card border border-emerald-200 bg-emerald-50 p-4">
            <span className="rounded-full bg-emerald-100 p-1.5">
              <CheckCheck className="h-4 w-4 text-emerald-700" aria-hidden="true" />
            </span>
            <div>
              <p className="text-sm font-semibold text-emerald-900">Todo al día</p>
              <p className="text-xs text-emerald-800">
                Sin pedidos con faltante, sin envíos detenidos y con el ERP conectado.
              </p>
            </div>
          </div>
        ) : (
          <div className="card-flush divide-y divide-slate-100">
            {attention.map(({ id, tone, count, label, hint, to, Icon }) => (
              <Link
                key={id}
                to={to}
                className="flex min-h-touch items-center gap-3 px-4 py-3 transition first:rounded-t-card last:rounded-b-card hover:bg-slate-50"
              >
                <span className={`rounded-full p-1.5 ${TONE_ROW[tone].icon}`}>
                  <Icon className="h-4 w-4" aria-hidden="true" />
                </span>
                <span
                  className={`min-w-[2ch] text-lg font-bold tabular-nums ${TONE_ROW[tone].count}`}
                >
                  {count}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-slate-900">{label}</span>
                  <span className="block truncate text-xs text-slate-500">{hint}</span>
                </span>
                <ChevronRight className="h-4 w-4 shrink-0 text-slate-400" aria-hidden="true" />
              </Link>
            ))}
          </div>
        )}
      </section>

      {/* 2. Cómo viene el día: cuatro cifras, no más */}
      <section className="mb-6">
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
          Pedidos
        </h2>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <MetricCard
            label="Por procesar"
            value={o.por_procesar}
            hint="Importados y pendientes de picking"
            tone={o.por_procesar > 0 ? 'warn' : 'neutral'}
            icon={ClipboardList}
            to="/orders"
          />
          <MetricCard
            label="En proceso"
            value={o.en_proceso}
            hint="En picking o packing"
            tone="info"
            icon={PackageSearch}
            to="/picking"
          />
          <MetricCard
            label="Listos p/ despacho"
            value={o.listos_despacho}
            hint="Esperando salida"
            tone={o.listos_despacho > 0 ? 'info' : 'neutral'}
            icon={PackageCheck}
            to="/dispatch"
          />
          <MetricCard
            label="Despachados hoy"
            value={o.despachados_hoy}
            hint={`${o.despachados} en total`}
            tone="ok"
            icon={Truck}
            to="/dispatch"
          />
        </div>
      </section>

      {/* 3. Cola de trabajo */}
      <section className="mb-6">
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
          Trabajo en curso
        </h2>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <MetricCard
            label="Picking abiertas"
            value={op.picking_abiertas}
            hint="Tareas pendientes, en curso o pausadas"
            tone={op.picking_abiertas > 0 ? 'info' : 'neutral'}
            icon={PackageSearch}
            to="/picking"
          />
          <MetricCard
            label="Packing abiertas"
            value={op.packing_abiertas}
            hint="Tareas pendientes o en curso"
            tone={op.packing_abiertas > 0 ? 'info' : 'neutral'}
            icon={PackageCheck}
            to="/packing"
          />
          <MetricCard
            label="Envíos al ERP en cola"
            value={op.sync_pendientes}
            hint="Recepciones, ajustes y pedidos por enviar"
            tone={op.sync_pendientes > 0 ? 'warn' : 'neutral'}
            icon={RefreshCw}
            to="/sync-jobs"
          />
          <MetricCard
            label="Pedidos vigentes"
            value={o.total}
            hint="Todos los estados"
            icon={ClipboardList}
            to="/orders"
          />
        </div>
      </section>

      {/* 4. Pedidos por estado */}
      <section className="mb-6">
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
          Pedidos por estado
        </h2>
        <div className="card">
          {estados.length === 0 ? (
            <p className="text-sm text-slate-500">Sin pedidos registrados.</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {estados.map(([status, count]) => (
                <Link
                  key={status}
                  to="/orders"
                  className="flex items-center gap-2 rounded-md border border-slate-200 px-3 py-2 transition hover:bg-slate-50"
                >
                  <StatusBadge status={status} />
                  <span className="text-base font-bold tabular-nums text-slate-900">{count}</span>
                </Link>
              ))}
            </div>
          )}
        </div>
      </section>

      {/* 5. Inventario e integración */}
      <section className="grid gap-3 lg:grid-cols-3">
        <div className="card lg:col-span-2">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
            Inventario
          </h2>
          <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <Stat label="Productos" value={inv.productos} Icon={Package} />
            <Stat label="Con stock" value={inv.con_stock} Icon={Boxes} />
            <Stat
              label="Sin stock"
              value={inv.sin_stock}
              Icon={PackageX}
              className={inv.sin_stock > 0 ? 'text-amber-900' : undefined}
            />
            <Stat label="Ubicaciones" value={inv.ubicaciones} Icon={MapPin} />
          </dl>
          <Link
            to="/inventory/erp-stock"
            className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-brand hover:underline"
          >
            Comparar con el stock de Defontana
            <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
          </Link>
        </div>

        <div className="card">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
            Defontana
          </h2>
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={defontana?.status ?? 'desconocido'} />
            {defontana?.mock && (
              <span className="badge bg-amber-100 text-amber-800">datos de prueba</span>
            )}
          </div>
          <dl className="mt-3 space-y-1 text-xs text-slate-500">
            {defontana?.environment && (
              <div className="flex justify-between gap-2">
                <dt>Entorno</dt>
                <dd className="code-strong text-xs">{defontana.environment}</dd>
              </div>
            )}
            <div className="flex justify-between gap-2">
              <dt>Último stock</dt>
              <dd className="text-slate-700">{fechaHora(defontana?.last_stock_sync_at)}</dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt>Últimos lotes</dt>
              <dd className="text-slate-700">{fechaHora(defontana?.last_lots_sync_at)}</dd>
            </div>
          </dl>
          {defontana && defontana.status !== 'connected' && (
            <p className="mt-2 flex items-start gap-1.5 text-xs text-amber-800">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
              Revisa la configuración: sin conexión no viajan recepciones ni ajustes.
            </p>
          )}
          <Link
            to="/settings/defontana"
            className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-brand hover:underline"
          >
            Configuración
            <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
          </Link>
        </div>
      </section>
    </div>
  );
}

function Stat({
  label,
  value,
  Icon,
  className,
}: {
  label: string;
  value: number;
  Icon: ComponentType<{ className?: string }>;
  className?: string;
}) {
  return (
    <div>
      <dt className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-slate-500">
        <Icon className="h-3.5 w-3.5 text-slate-400" aria-hidden="true" />
        {label}
      </dt>
      <dd className={`mt-0.5 text-xl font-bold tabular-nums ${className ?? 'text-slate-900'}`}>
        {value}
      </dd>
    </div>
  );
}
