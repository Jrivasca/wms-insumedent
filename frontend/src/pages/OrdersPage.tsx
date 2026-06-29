import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { createOrder, createPicking, getOrder, listOrders } from '../api/orders';
import { listPickingTasks } from '../api/picking';
import { errorMessage } from '../api/http';
import { Empty, ErrorBox, Loading, PageHeader } from '../components/Async';
import { Field, ProductPicker } from '../components/Form';
import StatusBadge from '../components/StatusBadge';
import { ERP_CREATE_ENABLED } from '../config';
import type { Order, PickingTask, Product } from '../types';

const CLOSED_PICKING = ['completed', 'completed_with_differences', 'cancelled'];

export default function OrdersPage() {
  const navigate = useNavigate();
  const [orders, setOrders] = useState<Order[]>([]);
  const [selected, setSelected] = useState<Order | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // order_id -> active (non-closed) picking task, to offer "Continuar picking".
  const [pickingByOrder, setPickingByOrder] = useState<Record<string, PickingTask>>({});

  // create-order state
  const [showCreate, setShowCreate] = useState(false);
  const [orderNum, setOrderNum] = useState('');
  const [customer, setCustomer] = useState('');
  const [orderLines, setOrderLines] = useState<{ product: Product | null; qty: string }[]>([
    { product: null, qty: '1' },
  ]);
  const [creating, setCreating] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [ords, tasks] = await Promise.all([
        listOrders(),
        listPickingTasks().catch(() => [] as PickingTask[]),
      ]);
      setOrders(ords);
      const map: Record<string, PickingTask> = {};
      for (const t of tasks) {
        if (!CLOSED_PICKING.includes(t.status)) map[t.order_id] = t;
      }
      setPickingByOrder(map);
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
      // Take the user straight to the picking task so the flow is obvious.
      navigate(`/my/picking/${task.id}`);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  function setLine(i: number, patch: Partial<{ product: Product | null; qty: string }>) {
    setOrderLines((ls) => ls.map((l, idx) => (idx === i ? { ...l, ...patch } : l)));
  }

  async function handleCreateOrder(e: React.FormEvent) {
    e.preventDefault();
    const lines = orderLines
      .filter((l) => l.product && Number(l.qty) > 0)
      .map((l) => ({ sku: l.product!.sku, name: l.product!.name, ordered_quantity: Number(l.qty) }));
    if (!orderNum.trim() || lines.length === 0) {
      setError('Ingrese el N° de pedido y al menos una línea con producto y cantidad.');
      return;
    }
    setCreating(true);
    setError(null);
    setNotice(null);
    try {
      const created = await createOrder({
        erp_order_number: orderNum.trim(),
        customer: customer.trim() || undefined,
        lines,
      });
      setNotice(`Pedido ${created.erp_order_number} creado · sincronización con ERP encolada`);
      setShowCreate(false);
      setOrderNum('');
      setCustomer('');
      setOrderLines([{ product: null, qty: '1' }]);
      load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setCreating(false);
    }
  }

  return (
    <div>
      <PageHeader
        title="Pedidos"
        subtitle="Gestión de pedidos y generación de picking"
        actions={
          ERP_CREATE_ENABLED ? (
            <button onClick={() => setShowCreate((v) => !v)} className="btn-primary">
              {showCreate ? 'Cerrar' : '+ Nuevo pedido'}
            </button>
          ) : undefined
        }
      />

      {notice && (
        <div className="mb-3 rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-700">{notice}</div>
      )}
      {error && <ErrorBox message={error} />}

      {ERP_CREATE_ENABLED && showCreate && (
        <form onSubmit={handleCreateOrder} className="card mb-4 space-y-3">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <Field label="N° de pedido *" value={orderNum} onChange={setOrderNum} required />
            <Field label="Cliente" value={customer} onChange={setCustomer} />
          </div>
          <div className="space-y-2">
            <label className="label">Líneas</label>
            {orderLines.map((l, i) => (
              <div key={i} className="flex items-end gap-2">
                <div className="flex-1">
                  <ProductPicker value={l.product} onChange={(p) => setLine(i, { product: p })} />
                </div>
                <div className="w-24">
                  <label className="label">Cantidad</label>
                  <input
                    type="number"
                    min={1}
                    value={l.qty}
                    onChange={(e) => setLine(i, { qty: e.target.value })}
                    className="input"
                  />
                </div>
                {orderLines.length > 1 && (
                  <button
                    type="button"
                    onClick={() => setOrderLines((ls) => ls.filter((_, idx) => idx !== i))}
                    className="btn-danger mb-0.5"
                  >
                    ✕
                  </button>
                )}
              </div>
            ))}
            <button
              type="button"
              onClick={() => setOrderLines((ls) => [...ls, { product: null, qty: '1' }])}
              className="text-sm font-medium text-brand underline"
            >
              + Agregar línea
            </button>
          </div>
          <button type="submit" className="btn-success" disabled={creating}>
            {creating ? 'Creando…' : 'Crear pedido y sincronizar'}
          </button>
        </form>
      )}

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
                {pickingByOrder[selected.id] ? (
                  <button
                    onClick={() => navigate(`/my/picking/${pickingByOrder[selected.id].id}`)}
                    className="btn-primary"
                  >
                    Continuar picking →
                  </button>
                ) : (
                  <button
                    onClick={() => handleGeneratePicking(selected.id)}
                    className="btn-primary"
                    disabled={busy}
                  >
                    {busy ? 'Generando…' : 'Generar picking'}
                  </button>
                )}
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
