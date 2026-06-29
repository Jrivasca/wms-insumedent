import { useEffect, useState } from 'react';
import { dispatchOrder, listDispatches } from '../api/dispatch';
import { listOrders } from '../api/orders';
import { errorMessage } from '../api/http';
import { Empty, ErrorBox, Loading, PageHeader } from '../components/Async';
import StatusBadge from '../components/StatusBadge';
import type { Dispatch, Order } from '../types';

export default function DispatchPage() {
  const [dispatches, setDispatches] = useState<Dispatch[]>([]);
  const [readyOrders, setReadyOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [activeOrder, setActiveOrder] = useState<string | null>(null);
  const [carrier, setCarrier] = useState('');
  const [tracking, setTracking] = useState('');
  const [busy, setBusy] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [d, orders] = await Promise.all([
        listDispatches().catch(() => [] as Dispatch[]),
        listOrders().catch(() => [] as Order[]),
      ]);
      setDispatches(d);
      setReadyOrders(orders.filter((o) => o.status === 'ready_to_dispatch'));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function confirmDispatch(orderId: string) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await dispatchOrder(orderId, {
        carrier: carrier.trim() || undefined,
        tracking_number: tracking.trim() || undefined,
      });
      setNotice('Despacho confirmado');
      setActiveOrder(null);
      setCarrier('');
      setTracking('');
      load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <PageHeader title="Despachos" subtitle="Confirmación y seguimiento de despachos" />

      {notice && (
        <div className="mb-3 rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-700">{notice}</div>
      )}
      {error && <ErrorBox message={error} />}

      <h2 className="mb-2 text-lg font-semibold">Pedidos listos para despachar</h2>
      {loading ? (
        <Loading />
      ) : readyOrders.length === 0 ? (
        <Empty label="No hay pedidos listos para despachar" />
      ) : (
        <div className="mb-6 space-y-3">
          {readyOrders.map((o) => (
            <div key={o.id} className="card">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <div className="font-bold">{o.erp_order_number}</div>
                  <div className="text-sm text-slate-500">{o.customer}</div>
                </div>
                {activeOrder === o.id ? null : (
                  <button onClick={() => setActiveOrder(o.id)} className="btn-primary">
                    Confirmar despacho
                  </button>
                )}
              </div>

              {activeOrder === o.id && (
                <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-3">
                  <div>
                    <label className="label">Transportista</label>
                    <input value={carrier} onChange={(e) => setCarrier(e.target.value)} className="input" />
                  </div>
                  <div>
                    <label className="label">N° seguimiento</label>
                    <input value={tracking} onChange={(e) => setTracking(e.target.value)} className="input" />
                  </div>
                  <div className="flex items-end gap-2">
                    <button onClick={() => confirmDispatch(o.id)} className="btn-success" disabled={busy}>
                      {busy ? 'Despachando…' : 'Despachar'}
                    </button>
                    <button onClick={() => setActiveOrder(null)} className="btn-secondary">
                      Cancelar
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <h2 className="mb-2 text-lg font-semibold">Despachos</h2>
      {dispatches.length === 0 ? (
        <Empty label="Sin despachos" />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="table w-full">
            <thead className="bg-slate-50">
              <tr>
                <th>ID</th>
                <th>Pedido</th>
                <th>Transportista</th>
                <th>Seguimiento</th>
                <th>Estado</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {dispatches.map((d) => (
                <tr key={d.id}>
                  <td className="font-mono text-xs">{d.id}</td>
                  <td>{d.order_id}</td>
                  <td>{d.carrier ?? '—'}</td>
                  <td>{d.tracking_number ?? '—'}</td>
                  <td>
                    <StatusBadge status={d.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
