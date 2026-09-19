import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Ban, CheckCheck, Tags, Truck, X } from 'lucide-react';
import { cancelOneDispatch, dispatchOrder, listDispatches } from '../api/dispatch';
import { listOrders } from '../api/orders';
import { listPackingTasks } from '../api/packing';
import { errorMessage } from '../api/http';
import { Empty, ErrorBox, LoadingRows, PageHeader } from '../components/Async';
import ConfirmDialog from '../components/ConfirmDialog';
import DataTable, { MobileCardList, type Column } from '../components/DataTable';
import Pager from '../components/Pager';
import StatusBadge from '../components/StatusBadge';
import { can } from '../permissions';
import { useAuth } from '../store/auth';
import type { Dispatch, Order, OrderLine } from '../types';

const PAGE = 50;
const CANCELLABLE = ['pending', 'sent_to_defontana', 'completed'];
const READY_STATES = ['ready_to_dispatch', 'partially_dispatched'];

function lineRemaining(l: OrderLine): number {
  return (l.packed_quantity ?? 0) - (l.dispatched_quantity ?? 0);
}
function remainingLines(o: Order) {
  return (o.lines ?? [])
    .map((l) => ({ sku: l.sku, name: l.name, remaining: lineRemaining(l) }))
    .filter((x) => x.remaining > 0);
}
function totalRemaining(o: Order): number {
  return (o.lines ?? []).reduce((s, l) => s + Math.max(0, lineRemaining(l)), 0);
}

export default function DispatchPage() {
  const navigate = useNavigate();
  const { currentUser } = useAuth();
  const canRevert = can(currentUser?.role); // admin / supervisor
  const [dispatches, setDispatches] = useState<Dispatch[]>([]);
  const [dispOffset, setDispOffset] = useState(0);
  const [dispTotal, setDispTotal] = useState(0);
  const [readyOrders, setReadyOrders] = useState<Order[]>([]);
  const [taskByOrder, setTaskByOrder] = useState<Record<string, string>>({});
  // order_id -> N° de pedido del ERP: en las guías el id interno no le dice nada a nadie.
  const [numberByOrder, setNumberByOrder] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [activeOrder, setActiveOrder] = useState<string | null>(null);
  const [guide, setGuide] = useState('');
  const [carrierChoice, setCarrierChoice] = useState('Bluexpress');
  const [carrierOther, setCarrierOther] = useState('');
  const [tracking, setTracking] = useState('');
  const [busy, setBusy] = useState(false);
  const [splitMode, setSplitMode] = useState(false);
  const [lineQtys, setLineQtys] = useState<Record<string, string>>({});
  const [toCancel, setToCancel] = useState<Dispatch | null>(null);

  const carrierValue = carrierChoice === 'Otro' ? carrierOther.trim() : carrierChoice;

  async function load(off = 0) {
    setLoading(true);
    setError(null);
    try {
      const [d, orders, tasks] = await Promise.all([
        listDispatches({ limit: PAGE, offset: off }).catch(() => null),
        // El endpoint filtra por un solo estado y aquí hacen falta dos, así que se
        // filtra en el cliente sobre la página que devuelve el backend.
        listOrders({ limit: 500 }).catch(() => null),
        listPackingTasks().catch(() => null),
      ]);
      setDispatches(d?.items ?? []);
      setDispTotal(d?.total ?? 0);
      setDispOffset(off);
      const allOrders = orders?.items ?? [];
      setReadyOrders(allOrders.filter((o) => READY_STATES.includes(o.status)));
      const numbers: Record<string, string> = {};
      for (const o of allOrders) numbers[o.id] = o.erp_order_number;
      setNumberByOrder(numbers);
      const map: Record<string, string> = {};
      for (const t of tasks?.items ?? []) map[t.order_id] = t.id;
      setTaskByOrder(map);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load(0);
  }, []);

  function openLabels(orderId: string) {
    const tid = taskByOrder[orderId];
    if (tid) navigate(`/my/packing/${tid}/labels`);
    else setNotice('No hay etiquetas de packing para este pedido.');
  }

  function openConfirm(o: Order) {
    setActiveOrder(o.id);
    setSplitMode(false);
    const init: Record<string, string> = {};
    for (const l of remainingLines(o)) init[l.sku] = String(l.remaining);
    setLineQtys(init);
    setGuide('');
    setCarrierChoice('Bluexpress');
    setCarrierOther('');
    setTracking('');
  }

  async function confirmDispatch(o: Order) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      let lines: { sku: string; quantity: number }[] | undefined;
      if (splitMode) {
        lines = remainingLines(o)
          .map((l) => ({ sku: l.sku, quantity: parseInt(lineQtys[l.sku] || '0', 10) || 0 }))
          .filter((l) => l.quantity > 0);
        if (lines.length === 0) {
          setError('Ingresa al menos una cantidad a despachar.');
          setBusy(false);
          return;
        }
      }
      await dispatchOrder(o.id, {
        guide_number: guide.trim() || undefined,
        carrier: carrierValue || undefined,
        tracking_number: tracking.trim() || undefined,
        lines,
      });
      setNotice(splitMode ? 'Despacho parcial confirmado' : 'Despacho confirmado');
      setActiveOrder(null);
      load(dispOffset);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleCancelGuide() {
    if (!toCancel) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await cancelOneDispatch(toCancel.id);
      setToCancel(null);
      setNotice('Guía anulada. Se revirtió su inventario y el pedido se recalculó.');
      load(dispOffset);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const orderNumber = (orderId: string) => numberByOrder[orderId] ?? orderId;

  const columns: Column<Dispatch>[] = [
    {
      key: 'order',
      header: 'Pedido',
      render: (d) => <span className="code-strong">{orderNumber(d.order_id)}</span>,
    },
    {
      key: 'guide',
      header: 'Guía',
      render: (d) =>
        d.guide_number ? (
          <span className="code-strong">{d.guide_number}</span>
        ) : (
          <span className="text-xs text-slate-400">sin guía</span>
        ),
    },
    { key: 'carrier', header: 'Transportista', render: (d) => d.carrier ?? '—' },
    {
      key: 'tracking',
      header: 'Seguimiento',
      secondary: true,
      render: (d) => (d.tracking_number ? <span className="code">{d.tracking_number}</span> : '—'),
    },
    { key: 'status', header: 'Estado', render: (d) => <StatusBadge status={d.status} /> },
    {
      key: 'actions',
      header: '',
      align: 'right',
      render: (d) => (
        <div className="flex flex-wrap justify-end gap-2">
          {taskByOrder[d.order_id] && (
            <button onClick={() => openLabels(d.order_id)} className="btn-secondary btn-sm">
              <Tags className="h-3.5 w-3.5" aria-hidden="true" />
              Etiquetas
            </button>
          )}
          {canRevert && CANCELLABLE.includes(d.status) && (
            <button
              onClick={() => setToCancel(d)}
              className="btn-secondary btn-sm text-red-700"
              disabled={busy}
            >
              <Ban className="h-3.5 w-3.5" aria-hidden="true" />
              Anular guía
            </button>
          )}
        </div>
      ),
    },
  ];

  return (
    <div>
      <PageHeader title="Despachos" subtitle="Confirma salidas y sigue las guías emitidas" />

      {notice && (
        <div className="mb-3 flex items-start gap-2 rounded-card border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
          <CheckCheck className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          {notice}
        </div>
      )}
      {error && <ErrorBox message={error} onRetry={() => load(dispOffset)} />}

      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
        Listos para despachar
      </h2>
      {loading ? (
        <LoadingRows rows={3} />
      ) : readyOrders.length === 0 ? (
        <Empty
          label="No hay pedidos listos para despachar"
          hint="Aquí aparecen los pedidos una vez terminado el packing."
        />
      ) : (
        <div className="mb-6 space-y-3">
          {readyOrders.map((o) => (
            <div key={o.id} className="card">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="code-strong text-base">{o.erp_order_number}</span>
                    {o.status === 'partially_dispatched' && (
                      <StatusBadge status="partially_dispatched" />
                    )}
                  </div>
                  <p className="mt-0.5 text-sm text-slate-500">
                    {o.customer || 'Sin cliente'} · quedan{' '}
                    <span className="font-semibold tabular-nums text-slate-700">
                      {totalRemaining(o)}
                    </span>{' '}
                    ítems por despachar
                  </p>
                </div>
                {activeOrder === o.id ? null : (
                  <div className="flex flex-wrap gap-2">
                    {taskByOrder[o.id] && (
                      <button onClick={() => openLabels(o.id)} className="btn-secondary">
                        <Tags className="h-4 w-4" aria-hidden="true" />
                        Etiquetas (QR)
                      </button>
                    )}
                    <button onClick={() => openConfirm(o)} className="btn-primary">
                      <Truck className="h-4 w-4" aria-hidden="true" />
                      Confirmar despacho
                    </button>
                  </div>
                )}
              </div>

              {activeOrder === o.id && (
                <div className="mt-4 space-y-3 border-t border-slate-200 pt-3">
                  <label className="flex min-h-touch items-start gap-2 text-sm text-slate-700">
                    <input
                      type="checkbox"
                      className="mt-1 h-4 w-4 rounded border-slate-300 text-brand focus:ring-brand"
                      checked={splitMode}
                      onChange={(e) => setSplitMode(e.target.checked)}
                    />
                    <span>
                      Despacho parcial: elegir cantidades por producto
                      <span className="block text-xs text-slate-500">
                        Puedes emitir varias guías para el mismo pedido.
                      </span>
                    </span>
                  </label>

                  {splitMode && (
                    <div className="space-y-2 rounded-card border border-slate-200 p-3">
                      {remainingLines(o).map((l) => (
                        <div key={l.sku} className="flex flex-wrap items-center gap-2">
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-sm text-slate-700">{l.name}</span>
                            <span className="code">{l.sku}</span>
                          </span>
                          <span className="text-xs text-slate-500">quedan {l.remaining}</span>
                          <input
                            type="number"
                            min={0}
                            max={l.remaining}
                            value={lineQtys[l.sku] ?? ''}
                            onChange={(e) =>
                              setLineQtys((s) => ({ ...s, [l.sku]: e.target.value }))
                            }
                            className="input input-lg w-24"
                            aria-label={`Cantidad a despachar de ${l.sku}`}
                          />
                        </div>
                      ))}
                    </div>
                  )}

                  <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
                    <div>
                      <label className="label" htmlFor={`guide-${o.id}`}>
                        N° guía de despacho
                      </label>
                      <input
                        id={`guide-${o.id}`}
                        value={guide}
                        onChange={(e) => setGuide(e.target.value)}
                        placeholder="Ingresa la guía"
                        className="input"
                      />
                      <p className="hint">Creada en Defontana (por ahora manual). Opcional.</p>
                    </div>
                    <div>
                      <label className="label" htmlFor={`carrier-${o.id}`}>
                        Transportista (opcional)
                      </label>
                      <select
                        id={`carrier-${o.id}`}
                        value={carrierChoice}
                        onChange={(e) => setCarrierChoice(e.target.value)}
                        className="input"
                      >
                        <option value="Bluexpress">Bluexpress</option>
                        <option value="NewTrans">NewTrans</option>
                        <option value="Otro">Otro…</option>
                      </select>
                      {carrierChoice === 'Otro' && (
                        <input
                          value={carrierOther}
                          onChange={(e) => setCarrierOther(e.target.value)}
                          placeholder="Nombre del transportista"
                          className="input mt-2"
                          aria-label="Nombre del transportista"
                        />
                      )}
                    </div>
                    <div>
                      <label className="label" htmlFor={`tracking-${o.id}`}>
                        N° seguimiento (opcional)
                      </label>
                      <input
                        id={`tracking-${o.id}`}
                        value={tracking}
                        onChange={(e) => setTracking(e.target.value)}
                        className="input"
                      />
                    </div>
                  </div>

                  <div className="flex flex-wrap gap-2">
                    <button
                      onClick={() => confirmDispatch(o)}
                      className="btn-success"
                      disabled={busy}
                    >
                      <Truck className="h-4 w-4" aria-hidden="true" />
                      {busy ? 'Despachando…' : splitMode ? 'Despachar lo indicado' : 'Despachar'}
                    </button>
                    <button onClick={() => setActiveOrder(null)} className="btn-secondary">
                      <X className="h-4 w-4" aria-hidden="true" />
                      Cancelar
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <h2 className="mb-2 mt-6 text-sm font-semibold uppercase tracking-wide text-slate-500">
        Guías emitidas
      </h2>
      {dispatches.length === 0 ? (
        <Empty label="Sin despachos" hint="Las guías confirmadas quedan registradas acá." />
      ) : (
        <>
          <div className="hidden lg:block">
            <DataTable columns={columns} rows={dispatches} keyOf={(d) => d.id} />
          </div>
          <div className="lg:hidden">
            <MobileCardList
              rows={dispatches}
              keyOf={(d) => d.id}
              render={(d) => (
                <div>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="code-strong">{orderNumber(d.order_id)}</span>
                    <StatusBadge status={d.status} />
                  </div>
                  <p className="mt-1 text-xs text-slate-500">
                    Guía {d.guide_number ? <span className="code">{d.guide_number}</span> : '—'}
                    {d.carrier && <> · {d.carrier}</>}
                    {d.tracking_number && (
                      <>
                        {' '}
                        · seguimiento <span className="code">{d.tracking_number}</span>
                      </>
                    )}
                  </p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {taskByOrder[d.order_id] && (
                      <button
                        onClick={() => openLabels(d.order_id)}
                        className="btn-secondary btn-sm"
                      >
                        <Tags className="h-3.5 w-3.5" aria-hidden="true" />
                        Etiquetas
                      </button>
                    )}
                    {canRevert && CANCELLABLE.includes(d.status) && (
                      <button
                        onClick={() => setToCancel(d)}
                        className="btn-secondary btn-sm text-red-700"
                        disabled={busy}
                      >
                        <Ban className="h-3.5 w-3.5" aria-hidden="true" />
                        Anular guía
                      </button>
                    )}
                  </div>
                </div>
              )}
            />
          </div>

          <div className="mt-3">
            <Pager
              offset={dispOffset}
              pageSize={PAGE}
              count={dispatches.length}
              total={dispTotal}
              onPrev={() => load(Math.max(0, dispOffset - PAGE))}
              onNext={() => load(dispOffset + PAGE)}
            />
          </div>
        </>
      )}

      <ConfirmDialog
        open={toCancel !== null}
        title="¿Anular esta guía?"
        message={
          toCancel
            ? `Se revierte el inventario que salió con la guía ${
                toCancel.guide_number ?? 'sin número'
              } del pedido ${orderNumber(toCancel.order_id)}, y el pedido se recalcula: vuelve a quedar con ítems por despachar.`
            : ''
        }
        confirmLabel="Anular guía"
        cancelLabel="Volver"
        busy={busy}
        onConfirm={handleCancelGuide}
        onCancel={() => setToCancel(null)}
      />
    </div>
  );
}
