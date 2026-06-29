import { useEffect, useState } from 'react';
import { listProducts } from '../api/products';
import { listOrders } from '../api/orders';
import { listSyncJobs } from '../api/syncJobs';
import { getDefontanaStatus } from '../api/integrations';
import { ErrorBox, Loading, PageHeader } from '../components/Async';
import StatusBadge from '../components/StatusBadge';
import { errorMessage } from '../api/http';
import type { DefontanaStatus, Order, SyncJob } from '../types';

interface Stats {
  products: number;
  ordersByStatus: Record<string, number>;
  pendingSync: number;
  defontana: DefontanaStatus | null;
}

export default function DashboardPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [products, orders, jobs, defontana] = await Promise.all([
        listProducts().catch(() => [] as never[]),
        listOrders().catch(() => [] as Order[]),
        listSyncJobs().catch(() => [] as SyncJob[]),
        getDefontanaStatus().catch(() => null),
      ]);

      const ordersByStatus: Record<string, number> = {};
      for (const o of orders) {
        ordersByStatus[o.status] = (ordersByStatus[o.status] ?? 0) + 1;
      }
      const pendingSync = jobs.filter(
        (j) => j.status === 'pending' || j.status === 'queued' || j.status === 'retrying'
      ).length;

      setStats({ products: products.length, ordersByStatus, pendingSync, defontana });
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

  return (
    <div>
      <PageHeader title="Dashboard" subtitle="Resumen operacional" />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card title="Productos" value={stats.products} />
        <Card
          title="Pedidos totales"
          value={Object.values(stats.ordersByStatus).reduce((a, b) => a + b, 0)}
        />
        <Card title="Sync pendientes" value={stats.pendingSync} highlight={stats.pendingSync > 0} />
        <div className="card">
          <p className="text-sm text-slate-500">Defontana</p>
          <div className="mt-2">
            <StatusBadge status={stats.defontana?.status ?? 'desconocido'} />
            {stats.defontana?.mock && (
              <span className="badge ml-2 bg-slate-100 text-slate-600">mock</span>
            )}
          </div>
          {stats.defontana?.environment && (
            <p className="mt-1 text-xs text-slate-400">Entorno: {stats.defontana.environment}</p>
          )}
          {stats.defontana?.last_error && (
            <p className="mt-1 text-xs text-red-500">{stats.defontana.last_error}</p>
          )}
        </div>
      </div>

      <div className="mt-6">
        <h2 className="mb-2 text-lg font-semibold">Pedidos por estado</h2>
        <div className="card">
          {Object.keys(stats.ordersByStatus).length === 0 ? (
            <p className="text-sm text-slate-400">Sin pedidos</p>
          ) : (
            <div className="flex flex-wrap gap-3">
              {Object.entries(stats.ordersByStatus).map(([status, count]) => (
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

function Card({
  title,
  value,
  highlight,
}: {
  title: string;
  value: number;
  highlight?: boolean;
}) {
  return (
    <div className={`card ${highlight ? 'border-amber-300 bg-amber-50' : ''}`}>
      <p className="text-sm text-slate-500">{title}</p>
      <p className="mt-1 text-3xl font-bold">{value}</p>
    </div>
  );
}
