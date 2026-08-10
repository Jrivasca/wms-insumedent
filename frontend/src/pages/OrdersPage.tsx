import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  createOrder,
  createPicking,
  getOrder,
  listOrders,
  reopenPacking,
  reopenPicking,
  updateOrder,
} from '../api/orders';
import { cancelDispatch } from '../api/dispatch';
import { listPickingTasks } from '../api/picking';
import { listPackingTasks } from '../api/packing';
import { errorMessage } from '../api/http';
import { Empty, ErrorBox, Loading, PageHeader } from '../components/Async';
import { Field, ProductPicker } from '../components/Form';
import Pager from '../components/Pager';
import StatusBadge from '../components/StatusBadge';
import { ERP_CREATE_ENABLED, PDF_IMPORT_ENABLED } from '../config';
import { can } from '../permissions';
import { useAuth } from '../store/auth';
import type { Order, PickingTask, Product } from '../types';

const CLOSED_PICKING = ['completed', 'completed_with_differences', 'cancelled'];
const PAGE = 50;

export default function OrdersPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { currentUser } = useAuth();
  const canEdit = can(currentUser?.role); // admin / supervisor
  const [orders, setOrders] = useState<Order[]>([]);
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const [selected, setSelected] = useState<Order | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // order_id -> active (non-closed) picking task, to offer "Continuar picking".
  const [pickingByOrder, setPickingByOrder] = useState<Record<string, PickingTask>>({});
  // order_id -> packing task id, to offer "Ir a packing" once picking is done.
  const [packingByOrder, setPackingByOrder] = useState<Record<string, string>>({});

  // create-order state
  const [showCreate, setShowCreate] = useState(false);
  const [orderNum, setOrderNum] = useState('');
  const [customer, setCustomer] = useState('');
  const [orderLines, setOrderLines] = useState<{ product: Product | null; qty: string }[]>([
    { product: null, qty: '1' },
  ]);
  const [creating, setCreating] = useState(false);

  // edit-order state (solo admin/supervisor, sólo pedidos en 'imported')
  const [editOrder, setEditOrder] = useState<Order | null>(null);
  const [editCustomer, setEditCustomer] = useState('');
  const [editLines, setEditLines] = useState<{ product: Product | null; qty: string }[]>([]);
  const [savingEdit, setSavingEdit] = useState(false);

  async function load(off = 0) {
    setLoading(true);
    setError(null);
    try {
      const [ords, tasks, packs] = await Promise.all([
        listOrders({ limit: PAGE, offset: off }),
        listPickingTasks().catch(() => null),
        listPackingTasks().catch(() => null),
      ]);
      setOrders(ords.items);
      setTotal(ords.total);
      setOffset(off);
      const map: Record<string, PickingTask> = {};
      for (const t of tasks?.items ?? []) {
        if (!CLOSED_PICKING.includes(t.status)) map[t.order_id] = t;
      }
      setPickingByOrder(map);
      const pmap: Record<string, string> = {};
      for (const t of packs?.items ?? []) {
        if (t.status !== 'cancelled') pmap[t.order_id] = t.id;
      }
      setPackingByOrder(pmap);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // Aviso de éxito traído desde el flujo de importación por PDF.
    const st = location.state as { notice?: string } | null;
    if (st?.notice) {
      setNotice(st.notice);
      navigate(location.pathname, { replace: true, state: null });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function openDetail(id: string) {
    setNotice(null);
    try {
      setSelected(await getOrder(id));
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function handleRevert(kind: 'dispatch' | 'packing' | 'picking', orderId: string) {
    const labels = {
      dispatch: 'anular el despacho (vuelve a «listo para despacho»)',
      packing: 'reabrir el packing (vuelve a «packing»; el inventario se ajusta automáticamente)',
      picking:
        'reabrir el picking (vuelve a «picking», se cancela el packing y el inventario se ajusta automáticamente)',
    };
    if (!window.confirm(`¿Confirmas ${labels[kind]}?`)) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      if (kind === 'dispatch') await cancelDispatch(orderId);
      else if (kind === 'packing') await reopenPacking(orderId);
      else await reopenPicking(orderId);
      setNotice(
        kind === 'dispatch'
          ? 'Despacho anulado. El pedido volvió a «listo para despacho».'
          : 'Pedido retrocedido de etapa. El inventario se ajustó automáticamente.'
      );
      await load(offset);
      openDetail(orderId);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
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

  function openEdit(o: Order) {
    setEditOrder(o);
    setEditCustomer(o.customer ?? '');
    setEditLines(
      o.lines.map((l) => ({
        product: { id: l.product_id ?? '', sku: l.sku, name: l.name, barcodes: [] } as Product,
        qty: String(l.ordered_quantity),
      }))
    );
    setError(null);
  }

  function setEditLine(i: number, patch: Partial<{ product: Product | null; qty: string }>) {
    setEditLines((ls) => ls.map((l, idx) => (idx === i ? { ...l, ...patch } : l)));
  }

  async function handleSaveEdit() {
    if (!editOrder) return;
    const lines = editLines
      .filter((l) => l.product && Number(l.qty) > 0)
      .map((l) => ({ sku: l.product!.sku, name: l.product!.name, ordered_quantity: Number(l.qty) }));
    if (lines.length === 0) {
      setError('El pedido debe tener al menos una línea con producto y cantidad.');
      return;
    }
    setSavingEdit(true);
    setError(null);
    setNotice(null);
    try {
      await updateOrder(editOrder.id, { customer: editCustomer.trim() || undefined, lines });
      setNotice(`Pedido ${editOrder.erp_order_number} actualizado`);
      const oid = editOrder.id;
      setEditOrder(null);
      await load();
      openDetail(oid);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSavingEdit(false);
    }
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
      setNotice(`Pedido ${created.erp_order_number} creado`);
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
          <>
            {PDF_IMPORT_ENABLED && (
              <button onClick={() => navigate('/orders/import')} className="btn-primary">
                Importar desde PDF
              </button>
            )}
            {ERP_CREATE_ENABLED && (
              <button onClick={() => setShowCreate((v) => !v)} className="btn-secondary">
                {showCreate ? 'Cerrar' : '+ Nuevo pedido'}
              </button>
            )}
          </>
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
            {creating ? 'Creando…' : 'Crear pedido'}
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
          <div className="mt-2">
            <Pager
              offset={offset}
              pageSize={PAGE}
              count={orders.length}
              total={total}
              onPrev={() => load(Math.max(0, offset - PAGE))}
              onNext={() => load(offset + PAGE)}
            />
          </div>
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

              <div className="mt-4 flex flex-wrap gap-2">
                {pickingByOrder[selected.id] ? (
                  <button
                    onClick={() => navigate(`/my/picking/${pickingByOrder[selected.id].id}`)}
                    className="btn-primary"
                  >
                    Continuar picking →
                  </button>
                ) : ['imported', 'pending_picking'].includes(selected.status) ? (
                  <button
                    onClick={() => handleGeneratePicking(selected.id)}
                    className="btn-primary"
                    disabled={busy}
                  >
                    {busy ? 'Generando…' : 'Generar picking'}
                  </button>
                ) : ['picked', 'packing', 'packed'].includes(selected.status) && packingByOrder[selected.id] ? (
                  <button
                    onClick={() => navigate(`/my/packing/${packingByOrder[selected.id]}`)}
                    className="btn-primary"
                  >
                    Ir a packing →
                  </button>
                ) : selected.status === 'ready_to_dispatch' ? (
                  <button onClick={() => navigate('/dispatch')} className="btn-primary">
                    Ir a despacho →
                  </button>
                ) : null}
                {canEdit && selected.status === 'imported' && (
                  <button onClick={() => openEdit(selected)} className="btn-secondary">
                    Editar pedido
                  </button>
                )}
              </div>

              {/* Retroceso de etapa (solo admin/supervisor). */}
              {canEdit &&
                ['picked', 'packing', 'packed', 'ready_to_dispatch', 'dispatched'].includes(
                  selected.status
                ) && (
                  <div className="mt-3 border-t border-slate-200 pt-3">
                    <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
                      Retroceso
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {selected.status === 'dispatched' && (
                        <button
                          onClick={() => handleRevert('dispatch', selected.id)}
                          className="btn-danger"
                          disabled={busy}
                        >
                          ↩ Anular despacho
                        </button>
                      )}
                      {selected.status === 'ready_to_dispatch' && (
                        <button
                          onClick={() => handleRevert('packing', selected.id)}
                          className="btn-secondary"
                          disabled={busy}
                        >
                          ↩ Reabrir packing
                        </button>
                      )}
                      {['picked', 'packing', 'packed', 'ready_to_dispatch'].includes(
                        selected.status
                      ) && (
                        <button
                          onClick={() => handleRevert('picking', selected.id)}
                          className="btn-secondary"
                          disabled={busy}
                        >
                          ↩ Reabrir picking
                        </button>
                      )}
                    </div>
                  </div>
                )}
            </div>
          ) : (
            <div className="card text-sm text-slate-400">
              Seleccione un pedido para ver el detalle.
            </div>
          )}
        </div>
      </div>

      {editOrder && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-lg bg-white p-4">
            <h3 className="text-lg font-bold">Editar pedido {editOrder.erp_order_number}</h3>
            <p className="mb-3 text-xs text-slate-500">
              Solo se puede editar antes de generar el picking.
            </p>
            <Field label="Cliente" value={editCustomer} onChange={setEditCustomer} />
            <div className="mt-3 space-y-2">
              <label className="label">Líneas</label>
              {editLines.map((l, i) => (
                <div key={i} className="flex items-end gap-2">
                  <div className="flex-1">
                    <ProductPicker value={l.product} onChange={(p) => setEditLine(i, { product: p })} />
                  </div>
                  <div className="w-24">
                    <label className="label">Cantidad</label>
                    <input
                      type="number"
                      min={1}
                      value={l.qty}
                      onChange={(e) => setEditLine(i, { qty: e.target.value })}
                      className="input"
                    />
                  </div>
                  {editLines.length > 1 && (
                    <button
                      type="button"
                      onClick={() => setEditLines((ls) => ls.filter((_, idx) => idx !== i))}
                      className="btn-danger mb-0.5"
                    >
                      ✕
                    </button>
                  )}
                </div>
              ))}
              <button
                type="button"
                onClick={() => setEditLines((ls) => [...ls, { product: null, qty: '1' }])}
                className="text-sm font-medium text-brand underline"
              >
                + Agregar línea
              </button>
            </div>
            <div className="mt-4 flex gap-2">
              <button onClick={handleSaveEdit} className="btn-success flex-1" disabled={savingEdit}>
                {savingEdit ? 'Guardando…' : 'Guardar cambios'}
              </button>
              <button onClick={() => setEditOrder(null)} className="btn-secondary flex-1">
                Cancelar
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
