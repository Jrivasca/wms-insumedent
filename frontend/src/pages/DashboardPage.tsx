import { useEffect, useState, type ReactNode } from 'react';
import { getDashboardStats } from '../api/dashboard';
import { getDefontanaStatus } from '../api/integrations';
import { ErrorBox, Loading, PageHeader } from '../components/Async';
import StatusBadge from '../components/StatusBadge';
import { errorMessage } from '../api/http';
import type { DashboardStats, DefontanaStatus } from '../types';

type Accent = 'amber' | 'blue' | 'violet' | 'emerald' | 'red';

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
  const estados = Object.entries(o.por_estado).filter(([, n]) => n > 0);

  return (
    <div>
      <PageHeader
        title="Dashboard"
        subtitle="Resumen operacional"
        actions={
          <button onClick={load} className="btn-secondary">
            Refrescar
          </button>
        }
      />

      <Section title="Pedidos">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <Card title="Total" value={o.total} />
          <Card title="Por procesar" value={o.por_procesar} accent="amber" />
          <Card title="En proceso" value={o.en_proceso} accent="blue" />
          <Card title="Listos p/ despacho" value={o.listos_despacho} accent="violet" />
          <Card title="Parciales / con faltante" value={o.parciales} accent={o.parciales > 0 ? 'amber' : undefined} />
          <Card title="Despacho parcial" value={o.despacho_parcial} accent={o.despacho_parcial > 0 ? 'amber' : undefined} />
          <Card title="Despachados" value={o.despachados} accent="emerald" />
          <Card title="Despachados hoy" value={o.despachados_hoy} accent="emerald" />
        </div>
        {o.error_cancelados > 0 && (
          <p className="mt-2 text-xs text-red-500">
            {o.error_cancelados} pedido(s) cancelado(s) o con error de sincronización.
          </p>
        )}
      </Section>

      <Section title="Inventario">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          <Card title="Productos" value={inv.productos} />
          <Card title="Sin stock" value={inv.sin_stock} accent={inv.sin_stock > 0 ? 'red' : undefined} />
          <Card title="Con stock" value={inv.con_stock} accent="emerald" />
          <Card title="Ubicaciones" value={inv.ubicaciones} />
        </div>
      </Section>

      <Section title="Operación">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          <Card title="Picking abiertas" value={op.picking_abiertas} accent={op.picking_abiertas > 0 ? 'blue' : undefined} />
          <Card title="Packing abiertas" value={op.packing_abiertas} accent={op.packing_abiertas > 0 ? 'blue' : undefined} />
          <Card title="Sync pendientes" value={op.sync_pendientes} accent={op.sync_pendientes > 0 ? 'amber' : undefined} />
          <div className="card">
            <p className="text-sm text-slate-500">Defontana</p>
            <div className="mt-2">
              <StatusBadge status={defontana?.status ?? 'desconocido'} />
              {defontana?.mock && (
                <span className="badge ml-2 bg-slate-100 text-slate-600">mock</span>
              )}
            </div>
            {defontana?.environment && (
              <p className="mt-1 text-xs text-slate-400">Entorno: {defontana.environment}</p>
            )}
          </div>
        </div>
      </Section>

      <div className="mt-6">
        <h2 className="mb-2 text-lg font-semibold">Pedidos por estado</h2>
        <div className="card">
          {estados.length === 0 ? (
            <p className="text-sm text-slate-400">Sin pedidos</p>
          ) : (
            <div className="flex flex-wrap gap-3">
              {estados.map(([status, count]) => (
                <div
                  key={status}
                  className="flex items-center gap-2 rounded-md border border-slate-200 px-3 py-2"
                >
                  <StatusBadge status={status} />
                  <span className="text-lg font-bold">{count}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="mt-6 first:mt-0">
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">{title}</h2>
      {children}
    </div>
  );
}

const ACCENTS: Record<Accent, string> = {
  amber: 'border-amber-300 bg-amber-50',
  blue: 'border-blue-300 bg-blue-50',
  violet: 'border-violet-300 bg-violet-50',
  emerald: 'border-emerald-300 bg-emerald-50',
  red: 'border-red-300 bg-red-50',
};

function Card({ title, value, accent }: { title: string; value: number; accent?: Accent }) {
  return (
    <div className={`card ${accent ? ACCENTS[accent] : ''}`}>
      <p className="text-sm text-slate-500">{title}</p>
      <p className="mt-1 text-3xl font-bold">{value}</p>
    </div>
  );
}
