import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { cancelOneDispatch, dispatchOrder, listDispatches } from '../api/dispatch';
import { listOrders } from '../api/orders';
import { listPackingTasks } from '../api/packing';
import { errorMessage } from '../api/http';
import { Empty, ErrorBox, Loading, PageHeader } from '../components/Async';
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

  const carrierValue = carrierChoice === 'Otro' ? carrierOther.trim() : carrierChoice;

  async function load(off = 0) {
    setLoading(true);
    setError(null);
    try {
      const [d, orders, tasks] = await Promise.all([
        listDispatches({ limit: PAGE, offset: off }).catch(() => null),
        listOrders().catch(() => null),
        listPackingTasks().catch(() => null),
      ]);
      setDispatches(d?.items ?? []);
      setDispTotal(d?.total ?? 0);
      setDispOffset(off);
      setReadyOrders((orders?.items ?? []).filter((o) => READY_STATES.includes(o.status)));
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
          setError('Ingresá al menos una cantidad a despachar.');
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

  async function handleCancelGuide(dispatchId: string) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await cancelOneDispatch(dispatchId);
      setNotice('Guía anulada. Se revirtió su inventario y el pedido se recalculó.');
      load(dispOffset);
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
                  <div className="flex items-center gap-2">
                    <span className="font-bold">{o.erp_order_number}</span>
                    {o.status === 'partially_dispatched' && (
                      <span className="badge bg-orange-100 text-orange-800">Parcialmente despachado</span>
                    )}
                  </div>
                  <div className="text-sm text-slate-500">
                    {o.customer} · quedan {totalRemaining(o)} ítems por despachar
                  </div>
                </div>
                {activeOrder === o.id ? null : (
                  <div className="flex gap-2">
                    {taskByOrder[o.id] && (
                      <button onClick={() => openLabels(o.id)} className="btn-secondary">
                        Etiquetas (QR)
                      </button>
                    )}
                    <button onClick={() => openConfirm(o)} className="btn-primary">
                      Confirmar despacho
                    </button>
                  </div>
                )}
              </div>

              {activeOrder === o.id && (
                <div className="mt-3 space-y-3">
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={splitMode}
                      onChange={(e) => setSplitMode(e.target.checked)}
                    />
                    Despacho parcial: elegir cantidades por producto (podés emitir varias guías)
                  </label>
                  {splitMode && (
                    <div className="space-y-1 rounded-md border border-slate-200 p-2">
                      {remainingLines(o).map((l) => (
                        <div key={l.sku} className="flex items-center gap-2">
                          <span className="flex-1 text-sm">
                            {l.name}{' '}
                            <span className="font-mono text-xs text-slate-400">{l.sku}</span>
                          </span>
                          <span className="text-xs text-slate-400">quedan {l.remaining}</span>
                          <input
                            type="number"
                            min={0}
                            max={l.remaining}
                            value={lineQtys[l.sku] ?? ''}
                            onChange={(e) => setLineQtys((s) => ({ ...s, [l.sku]: e.target.value }))}
                            className="input w-20"
                          />
                        </div>
                      ))}
                    </div>
                  )}
                  <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
                  <div>
                    <label className="label">N° guía de despacho</label>
                    <input
                      value={guide}
                      onChange={(e) => setGuide(e.target.value)}
                      placeholder="Ingresa la guía"
                      className="input"
                    />
                    <p className="mt-1 text-xs text-slate-400">
                      Creada en Defontana (por ahora manual). Opcional.
                    </p>
                  </div>
                  <div>
                    <label className="label">Transportista (opcional)</label>
                    <select
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
                      />
                    )}
                  </div>
                  <div>
                    <label className="label">N° seguimiento (opcional)</label>
                    <input value={tracking} onChange={(e) => setTracking(e.target.value)} className="input" />
                  </div>
                  <div className="flex items-end gap-2">
                    <button onClick={() => confirmDispatch(o)} className="btn-success" disabled={busy}>
                      {busy ? 'Despachando…' : 'Despachar'}
                    </button>
                    <button onClick={() => setActiveOrder(null)} className="btn-secondary">
                      Cancelar
                    </button>
                  </div>
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
                <th>Pedido</th>
                <th>Guía</th>
                <th>Transportista</th>
                <th>Seguimiento</th>
                <th>Estado</th>
                <th></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {dispatches.map((d) => (
                <tr key={d.id}>
                  <td>{d.order_id}</td>
                  <td className="font-mono text-xs">{d.guide_number ?? '—'}</td>
                  <td>{d.carrier ?? '—'}</td>
                  <td>{d.tracking_number ?? '—'}</td>
                  <td>
                    <StatusBadge status={d.status} />
                  </td>
                  <td>
                    <div className="flex flex-wrap justify-end gap-2">
                      {taskByOrder[d.order_id] && (
                        <button onClick={() => openLabels(d.order_id)} className="btn-secondary">
                          Etiquetas (QR)
                        </button>
                      )}
                      {canRevert && CANCELLABLE.includes(d.status) && (
                        <button
                          onClick={() => handleCancelGuide(d.id)}
                          className="btn-danger"
                          disabled={busy}
                        >
                          Anular guía
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Pager
        offset={dispOffset}
        pageSize={PAGE}
        count={dispatches.length}
        total={dispTotal}
        onPrev={() => load(Math.max(0, dispOffset - PAGE))}
        onNext={() => load(dispOffset + PAGE)}
      />
    </div>
  );
}
