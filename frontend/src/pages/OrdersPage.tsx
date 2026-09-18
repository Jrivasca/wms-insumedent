import { useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  ArrowRight,
  CheckCheck,
  ChevronRight,
  FileText,
  Pencil,
  Plus,
  RotateCcw,
  Trash2,
  Undo2,
  X,
} from 'lucide-react';
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
import { Empty, ErrorBox, LoadingRows, PageHeader } from '../components/Async';
import ConfirmDialog from '../components/ConfirmDialog';
import DataTable, { MobileCardList, type Column } from '../components/DataTable';
import { Field, ProductPicker } from '../components/Form';
import Pager from '../components/Pager';
import ProgressBar from '../components/ProgressBar';
import SearchInput from '../components/SearchInput';
import StatusBadge from '../components/StatusBadge';
import { statusLabel } from '../lib/status';
import { ERP_CREATE_ENABLED, PDF_IMPORT_ENABLED } from '../config';
import { can } from '../permissions';
import { useAuth } from '../store/auth';
import type { Order, PickingTask, Product } from '../types';

const CLOSED_PICKING = ['completed', 'completed_with_differences', 'cancelled'];
const PAGE = 50;

/** Estados de pedido que acepta el backend para filtrar; los valores no cambian. */
const ORDER_STATUSES = [
  'imported',
  'pending_picking',
  'picking',
  'picked',
  'packing',
  'packed',
  'ready_to_dispatch',
  'partially_dispatched',
  'dispatched',
  'sync_error',
  'cancelled',
];

type RevertKind = 'dispatch' | 'packing' | 'picking';

const REVERT: Record<RevertKind, { title: string; message: string; confirmLabel: string }> = {
  dispatch: {
    title: '¿Anular el despacho?',
    message: 'El pedido vuelve a «Listo para despacho».',
    confirmLabel: 'Anular despacho',
  },
  packing: {
    title: '¿Reabrir el packing?',
    message:
      'El pedido vuelve a «En packing» y el inventario se ajusta automáticamente para reflejarlo.',
    confirmLabel: 'Reabrir packing',
  },
  picking: {
    title: '¿Reabrir el picking?',
    message:
      'El pedido vuelve a «En picking», se cancela el packing y el inventario se ajusta automáticamente.',
    confirmLabel: 'Reabrir picking',
  },
};

/** Marca visible de pedido incompleto por falta de stock (eje fulfillment). */
function PartialPill({ order }: { order: Order }) {
  if (order.fulfillment !== 'partial') return null;
  return (
    <span
      className="badge bg-amber-100 text-amber-900"
      title="Pedido incompleto: se cumplió menos de lo pedido por falta de stock"
    >
      Parcial
    </span>
  );
}

/** El pedido cambió en Defontana (anulado, cerrado, guía emitida allá…) estando en preparación. */
function ErpChangedPill({ order }: { order: Order }) {
  if (!order.erp_attention) return null;
  return (
    <span className="badge bg-amber-100 text-amber-900" title={order.erp_attention.reason}>
      Cambió en Defontana
    </span>
  );
}

function orderProgress(o: Order): { picked: number; required: number } {
  return {
    required: o.lines.reduce((a, l) => a + l.ordered_quantity, 0),
    picked: o.lines.reduce((a, l) => a + (l.picked_quantity ?? 0), 0),
  };
}

export default function OrdersPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { currentUser } = useAuth();
  const canEdit = can(currentUser?.role); // admin / supervisor
  const [orders, setOrders] = useState<Order[]>([]);
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState('');
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<Order | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [revert, setRevert] = useState<{ kind: RevertKind; orderId: string } | null>(null);
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
        listOrders({ status: status || undefined, limit: PAGE, offset: off }),
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
    load(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);

  useEffect(() => {
    // Aviso de éxito traído desde el flujo de importación por PDF.
    const st = location.state as { notice?: string } | null;
    if (st?.notice) {
      setNotice(st.notice);
      navigate(location.pathname, { replace: true, state: null });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // El backend filtra por estado pero no busca por texto: esto filtra lo ya cargado.
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return orders;
    return orders.filter((o) =>
      [o.erp_order_number, o.customer].filter(Boolean).some((v) =>
        String(v).toLowerCase().includes(q)
      )
    );
  }, [orders, query]);

  async function openDetail(id: string) {
    setNotice(null);
    try {
      setSelected(await getOrder(id));
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function handleRevert() {
    if (!revert) return;
    const { kind, orderId } = revert;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      if (kind === 'dispatch') await cancelDispatch(orderId);
      else if (kind === 'packing') await reopenPacking(orderId);
      else await reopenPicking(orderId);
      setNotice(
        kind === 'dispatch'
          ? 'Despacho anulado. El pedido volvió a «Listo para despacho».'
          : 'Pedido retrocedido de etapa. El inventario se ajustó automáticamente.'
      );
      setRevert(null);
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
      await load(offset);
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
      load(offset);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setCreating(false);
    }
  }

  const columns: Column<Order>[] = [
    {
      key: 'number',
      header: 'N° ERP',
      render: (o) => <span className="code-strong">{o.erp_order_number}</span>,
    },
    {
      key: 'customer',
      header: 'Cliente',
      render: (o) => <span className="text-slate-700">{o.customer || '—'}</span>,
    },
    {
      key: 'status',
      header: 'Estado',
      render: (o) => (
        <div className="flex flex-wrap items-center gap-1">
          <StatusBadge status={o.status} />
          <PartialPill order={o} />
          <ErpChangedPill order={o} />
        </div>
      ),
    },
    {
      key: 'progress',
      header: 'Pickeado',
      width: '10rem',
      secondary: true,
      render: (o) => {
        const { picked, required } = orderProgress(o);
        return <ProgressBar value={picked} total={required} unit="u" compact />;
      },
    },
    {
      key: 'lines',
      header: 'Líneas',
      align: 'right',
      secondary: true,
      render: (o) => o.lines.length,
    },
    {
      key: 'go',
      header: '',
      align: 'right',
      width: '3rem',
      render: () => <ChevronRight className="inline h-4 w-4 text-slate-400" aria-hidden="true" />,
    },
  ];

  const revertCopy = revert ? REVERT[revert.kind] : null;
  const revertMessage =
    revert?.kind === 'dispatch' && selected?.status === 'partially_dispatched'
      ? `${REVERT.dispatch.message} Se anulan todas las guías emitidas.`
      : revertCopy?.message ?? '';

  return (
    <div>
      <PageHeader
        title="Pedidos"
        subtitle="Gestión de pedidos y generación de picking"
        actions={
          <>
            {PDF_IMPORT_ENABLED && (
              <button onClick={() => navigate('/orders/import')} className="btn-primary">
                <FileText className="h-4 w-4" aria-hidden="true" />
                Importar desde PDF
              </button>
            )}
            {ERP_CREATE_ENABLED && (
              <button onClick={() => setShowCreate((v) => !v)} className="btn-secondary">
                {showCreate ? (
                  <>
                    <X className="h-4 w-4" aria-hidden="true" />
                    Cerrar
                  </>
                ) : (
                  <>
                    <Plus className="h-4 w-4" aria-hidden="true" />
                    Nuevo pedido
                  </>
                )}
              </button>
            )}
            <button onClick={() => load(offset)} className="btn-secondary">
              <RotateCcw className="h-4 w-4" aria-hidden="true" />
              Refrescar
            </button>
          </>
        }
      />

      {notice && (
        <div className="mb-3 flex items-start gap-2 rounded-card border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
          <CheckCheck className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          {notice}
        </div>
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
                    className="btn-ghost mb-0.5 text-red-600 hover:bg-red-50"
                    aria-label={`Quitar línea ${i + 1}`}
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                )}
              </div>
            ))}
            <button
              type="button"
              onClick={() => setOrderLines((ls) => [...ls, { product: null, qty: '1' }])}
              className="inline-flex items-center gap-1 text-sm font-medium text-brand hover:underline"
            >
              <Plus className="h-4 w-4" aria-hidden="true" />
              Agregar línea
            </button>
          </div>
          <button type="submit" className="btn-success" disabled={creating}>
            {creating ? 'Creando…' : 'Crear pedido'}
          </button>
        </form>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div>
          <div className="mb-3 grid gap-2 sm:grid-cols-[13rem_1fr]">
            <div>
              <label className="label" htmlFor="order-status">
                Estado
              </label>
              <select
                id="order-status"
                value={status}
                onChange={(e) => setStatus(e.target.value)}
                className="input"
              >
                <option value="">Todos los estados</option>
                {ORDER_STATUSES.map((s) => (
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
              placeholder="N° de pedido o cliente…"
            />
          </div>

          {loading ? (
            <LoadingRows />
          ) : shown.length === 0 ? (
            <Empty
              label={orders.length === 0 ? 'No hay pedidos' : 'Ningún resultado'}
              hint={
                orders.length === 0
                  ? 'Los pedidos llegan desde Defontana o se importan desde PDF.'
                  : 'La búsqueda se aplica a los pedidos ya cargados en esta página.'
              }
            />
          ) : (
            <>
              <div className="hidden lg:block">
                <DataTable
                  columns={columns}
                  rows={shown}
                  keyOf={(o) => o.id}
                  onRowClick={(o) => openDetail(o.id)}
                  rowClassName={(o) => (selected?.id === o.id ? 'bg-brand-soft' : undefined)}
                />
              </div>
              <div className="lg:hidden">
                <MobileCardList
                  rows={shown}
                  keyOf={(o) => o.id}
                  render={(o) => {
                    const { picked, required } = orderProgress(o);
                    return (
                      <button
                        type="button"
                        onClick={() => openDetail(o.id)}
                        className="flex min-h-touch w-full items-center gap-3 text-left"
                      >
                        <span className="min-w-0 flex-1">
                          <span className="flex flex-wrap items-center gap-2">
                            <span className="code-strong">{o.erp_order_number}</span>
                            <StatusBadge status={o.status} />
                            <PartialPill order={o} />
                            <ErpChangedPill order={o} />
                          </span>
                          <span className="mt-1 block truncate text-xs text-slate-500">
                            {o.customer || 'Sin cliente'} · {o.lines.length} línea(s)
                          </span>
                          <span className="mt-1 block">
                            <ProgressBar value={picked} total={required} unit="u" />
                          </span>
                        </span>
                        <ChevronRight
                          className="h-5 w-5 shrink-0 text-slate-400"
                          aria-hidden="true"
                        />
                      </button>
                    );
                  }}
                />
              </div>
            </>
          )}

          {query.trim() !== '' && shown.length > 0 && (
            <p className="hint mt-2">
              Se muestran {shown.length} de los {orders.length} pedidos cargados en esta página.
            </p>
          )}

          <div className="mt-3">
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
            <div className="card lg:sticky lg:top-20">
              <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <h2 className="text-lg font-bold text-slate-900">
                    Pedido <span className="code-strong text-lg">{selected.erp_order_number}</span>
                  </h2>
                  <p className="text-sm text-slate-500">{selected.customer || 'Sin cliente'}</p>
                </div>
                <div className="flex flex-wrap items-center gap-1">
                  <StatusBadge status={selected.status} />
                  <PartialPill order={selected} />
                </div>
              </div>

              <div className="mb-3 text-xs text-slate-500">
                {selected.order_date && <span>Fecha: {selected.order_date} </span>}
                {selected.delivery_date && <span>· Entrega: {selected.delivery_date}</span>}
                {selected.erp_status && <span> · Defontana: {selected.erp_status}</span>}
              </div>

              {selected.erp_attention && (
                <div className="mb-3 rounded-card border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                  {selected.erp_attention.reason}. El pedido ya está en preparación: revisa si hay
                  que retrocederlo.
                </div>
              )}
              {selected.status === 'cancelled' && selected.cancel_reason && (
                <div className="mb-3 rounded-card bg-slate-100 px-3 py-2 text-sm text-slate-600">
                  Cancelado: {selected.cancel_reason}
                </div>
              )}

              <div className="overflow-x-auto">
                <table className="table w-full">
                  <thead className="border-b border-slate-200">
                    <tr>
                      <th>SKU</th>
                      <th>Producto</th>
                      <th className="text-right">Pedido</th>
                      <th className="text-right">Pickeado</th>
                      <th className="text-right">Empacado</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {selected.lines.map((l) => {
                      const missing = Math.max(0, l.ordered_quantity - (l.picked_quantity ?? 0));
                      return (
                        <tr key={l.line_id} className={missing > 0 ? 'bg-amber-50' : ''}>
                          <td className="code">{l.sku}</td>
                          <td>{l.name}</td>
                          <td className="text-right tabular-nums">
                            {l.ordered_quantity} {l.unit ?? ''}
                          </td>
                          <td
                            className={`text-right tabular-nums ${
                              missing > 0 ? 'font-semibold text-amber-900' : ''
                            }`}
                          >
                            {l.picked_quantity}
                            {missing > 0 && (
                              <span className="ml-1 text-xs font-normal text-amber-800">
                                (faltan {missing})
                              </span>
                            )}
                          </td>
                          <td className="text-right tabular-nums">{l.packed_quantity}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              <div className="mt-4 flex flex-wrap gap-2">
                {pickingByOrder[selected.id] ? (
                  <button
                    onClick={() => navigate(`/my/picking/${pickingByOrder[selected.id].id}`)}
                    className="btn-primary"
                  >
                    Continuar picking
                    <ArrowRight className="h-4 w-4" aria-hidden="true" />
                  </button>
                ) : ['imported', 'pending_picking'].includes(selected.status) ? (
                  <button
                    onClick={() => handleGeneratePicking(selected.id)}
                    className="btn-primary"
                    disabled={busy}
                  >
                    {busy ? 'Generando…' : 'Generar picking'}
                    {!busy && <ArrowRight className="h-4 w-4" aria-hidden="true" />}
                  </button>
                ) : ['picked', 'packing', 'packed'].includes(selected.status) &&
                  packingByOrder[selected.id] ? (
                  <button
                    onClick={() => navigate(`/my/packing/${packingByOrder[selected.id]}`)}
                    className="btn-primary"
                  >
                    Ir a packing
                    <ArrowRight className="h-4 w-4" aria-hidden="true" />
                  </button>
                ) : ['ready_to_dispatch', 'partially_dispatched'].includes(selected.status) ? (
                  <button onClick={() => navigate('/dispatch')} className="btn-primary">
                    Ir a despacho
                    <ArrowRight className="h-4 w-4" aria-hidden="true" />
                  </button>
                ) : null}
                {canEdit && selected.status === 'imported' && (
                  <button onClick={() => openEdit(selected)} className="btn-secondary">
                    <Pencil className="h-4 w-4" aria-hidden="true" />
                    Editar pedido
                  </button>
                )}
              </div>

              {/* Retroceso de etapa (solo admin/supervisor). */}
              {canEdit &&
                [
                  'picked',
                  'packing',
                  'packed',
                  'ready_to_dispatch',
                  'partially_dispatched',
                  'dispatched',
                ].includes(selected.status) && (
                  <div className="mt-4 border-t border-slate-200 pt-3">
                    <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                      Retroceder etapa
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {['dispatched', 'partially_dispatched'].includes(selected.status) && (
                        <button
                          onClick={() => setRevert({ kind: 'dispatch', orderId: selected.id })}
                          className="btn-secondary btn-sm text-red-700"
                          disabled={busy}
                        >
                          <Undo2 className="h-3.5 w-3.5" aria-hidden="true" />
                          Anular despacho
                        </button>
                      )}
                      {selected.status === 'ready_to_dispatch' && (
                        <button
                          onClick={() => setRevert({ kind: 'packing', orderId: selected.id })}
                          className="btn-secondary btn-sm"
                          disabled={busy}
                        >
                          <Undo2 className="h-3.5 w-3.5" aria-hidden="true" />
                          Reabrir packing
                        </button>
                      )}
                      {['picked', 'packing', 'packed', 'ready_to_dispatch'].includes(
                        selected.status
                      ) && (
                        <button
                          onClick={() => setRevert({ kind: 'picking', orderId: selected.id })}
                          className="btn-secondary btn-sm"
                          disabled={busy}
                        >
                          <Undo2 className="h-3.5 w-3.5" aria-hidden="true" />
                          Reabrir picking
                        </button>
                      )}
                    </div>
                  </div>
                )}
            </div>
          ) : (
            <div className="card">
              <Empty
                label="Ningún pedido abierto"
                hint="Elige un pedido de la lista para ver sus líneas y continuar el flujo."
              />
            </div>
          )}
        </div>
      </div>

      <ConfirmDialog
        open={revert !== null}
        title={revertCopy?.title ?? ''}
        message={revertMessage}
        confirmLabel={revertCopy?.confirmLabel ?? 'Confirmar'}
        busy={busy}
        onConfirm={handleRevert}
        onCancel={() => setRevert(null)}
      />

      {editOrder && (
        <div
          className="fixed inset-0 z-50 flex items-end justify-center bg-graphite-950/50 p-4 sm:items-center"
          role="dialog"
          aria-modal="true"
          aria-labelledby="edit-order-title"
        >
          <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-card bg-white p-5 shadow-raised">
            <h3 id="edit-order-title" className="text-lg font-bold text-slate-900">
              Editar pedido <span className="code-strong text-lg">{editOrder.erp_order_number}</span>
            </h3>
            <p className="mb-3 text-xs text-slate-500">
              Solo se puede editar antes de generar el picking.
            </p>
            <Field label="Cliente" value={editCustomer} onChange={setEditCustomer} />
            <div className="mt-3 space-y-2">
              <label className="label">Líneas</label>
              {editLines.map((l, i) => (
                <div key={i} className="flex items-end gap-2">
                  <div className="flex-1">
                    <ProductPicker
                      value={l.product}
                      onChange={(p) => setEditLine(i, { product: p })}
                    />
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
                      className="btn-ghost mb-0.5 text-red-600 hover:bg-red-50"
                      aria-label={`Quitar línea ${i + 1}`}
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  )}
                </div>
              ))}
              <button
                type="button"
                onClick={() => setEditLines((ls) => [...ls, { product: null, qty: '1' }])}
                className="inline-flex items-center gap-1 text-sm font-medium text-brand hover:underline"
              >
                <Plus className="h-4 w-4" aria-hidden="true" />
                Agregar línea
              </button>
            </div>
            <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button onClick={() => setEditOrder(null)} className="btn-secondary">
                Cancelar
              </button>
              <button onClick={handleSaveEdit} className="btn-primary" disabled={savingEdit}>
                {savingEdit ? 'Guardando…' : 'Guardar cambios'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
