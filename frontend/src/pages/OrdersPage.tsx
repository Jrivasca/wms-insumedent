import { useEffect, useState } from 'react';
import { createPicking, getOrder, listOrders } from '../api/orders';
import { errorMessage } from '../api/http';
import { Empty, ErrorBox, Loading, PageHeader } from '../components/Async';
import StatusBadge from '../components/StatusBadge';
import type { Order } from '../types';

export default function OrdersPage() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [selected, setSelected] = useState<Order | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setOrders(await listOrders());
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function openDetail(id: string) {
    setNotice(null);
    try {
      setSelected(await getOrder(id));
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function handleGeneratePicking(orderId: string) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const task = await createPicking(orderId);
      setNotice(`Picking generado (tarea ${task.id})`);
      load();
      if (selected?.id === orderId) openDetail(orderId);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <PageHeader title="Pedidos" subtitle="Gestión de pedidos y generación de picking" />

      {notice && (
        <div className="mb-3 rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-700">{notice}</div>
      )}
      {error && <ErrorBox message={error} />}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div>
          {loading ? (
            <Loading />
          ) : orders.length === 0 ? (
            <Empty label="No hay pedidos" />
          ) : (
            <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
              <table className="table w-full">
                <thead className="bg-slate-50">
                  <tr>
                    <th>N° ERP</th>
                    <th>Cliente</th>
                    <th>Estado</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {orders.map((o) => (
                    <tr key={o.id} className={selected?.id === o.id ? 'bg-blue-50' : ''}>
                      <td className="font-mono text-xs">{o.erp_order_number}</td>
                      <td>{o.customer}</td>
                      <td>
                        <StatusBadge status={o.status} />
                      </td>
                      <td>
                        <button onClick={() => openDetail(o.id)} className="btn-secondary">
                          Ver
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div>
          {selected ? (
            <div className="card">
              <div className="mb-3 flex items-center justify-between">
                <div>
                  <h2 className="text-lg font-bold">Pedido {selected.erp_order_number}</h2>
                  <p className="text-sm text-slate-500">{selected.customer}</p>
                </div>
                <StatusBadge status={selected.status} />
              </div>

              <div className="mb-3 text-xs text-slate-500">
                {selected.order_date && <span>Fecha: {selected.order_date} </span>}
                {selected.delivery_date && <span>· Entrega: {selected.delivery_date}</span>}
              </div>

              <table className="table w-full">
                <thead>
                  <tr>
                    <th>SKU</th>
                    <th>Producto</th>
                    <th>Pedido</th>
                    <th>Pickeado</th>
                    <th>Empacado</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {selected.lines.map((l) => (
                    <tr key={l.line_id}>
                      <td className="font-mono text-xs">{l.sku}</td>
                      <td>{l.name}</td>
                      <td>
                        {l.ordered_quantity} {l.unit ?? ''}
                      </td>
                      <td>{l.picked_quantity}</td>
                      <td>{l.packed_quantity}</td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <div className="mt-4">
                <button
                  onClick={() => handleGeneratePicking(selected.id)}
                  className="btn-primary"
                  disabled={busy}
                >
                  {busy ? 'Generando…' : 'Generar picking'}
                </button>
              </div>
            </div>
          ) : (
            <div className="card text-sm text-slate-400">
              Seleccione un pedido para ver el detalle.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
