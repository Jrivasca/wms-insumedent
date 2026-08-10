import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  completePicking,
  getPickingTask,
  markMissing,
  resetPickingLine,
  scanPicking,
  startPicking,
} from '../api/picking';
import { errorMessage } from '../api/http';
import { ErrorBox, Loading } from '../components/Async';
import BarcodeScanner, { ScanFeedback } from '../components/BarcodeScanner';
import StatusBadge from '../components/StatusBadge';
import Toast from '../components/Toast';
import type { PickingLine, PickingTask } from '../types';

export default function PickingTaskPage() {
  const { id = '' } = useParams();
  const navigate = useNavigate();

  const [task, setTask] = useState<PickingTask | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [messageTone, setMessageTone] = useState<'info' | 'success' | 'warning' | 'error'>('info');
  const [feedback, setFeedback] = useState<ScanFeedback>('idle');

  function showMessage(text: string, tone: 'info' | 'success' | 'warning' | 'error' = 'info') {
    setMessage(text);
    setMessageTone(tone);
  }
  const [quantity, setQuantity] = useState(1);
  const [busy, setBusy] = useState(false);
  // The operator can tap a line to pick it; otherwise we auto-focus the first pending one.
  const [selectedSku, setSelectedSku] = useState<string | null>(null);

  // missing modal
  const [missingFor, setMissingFor] = useState<PickingLine | null>(null);
  const [missingReason, setMissingReason] = useState('');

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const t = await getPickingTask(id);
      setTask(t);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  // The line the operator is picking: the one they tapped (if still pending), else
  // the first pending line.
  const currentLine = useMemo<PickingLine | null>(() => {
    if (!task) return null;
    const pending = (l: PickingLine) =>
      l.quantity_picked < l.quantity_required && l.status !== 'missing';
    if (selectedSku) {
      const sel = task.lines.find((l) => l.sku === selectedSku);
      if (sel && pending(sel)) return sel;
    }
    return task.lines.find(pending) ?? null;
  }, [task, selectedSku]);

  const progress = useMemo(() => {
    if (!task) return { picked: 0, total: 0, lines: 0, done: 0 };
    const total = task.lines.reduce((a, l) => a + l.quantity_required, 0);
    const picked = task.lines.reduce((a, l) => a + l.quantity_picked, 0);
    const done = task.lines.filter(
      (l) => l.quantity_picked >= l.quantity_required || l.status === 'missing'
    ).length;
    return { picked, total, lines: task.lines.length, done };
  }, [task]);

  async function handleStart() {
    setBusy(true);
    setError(null);
    try {
      const t = await startPicking(id);
      setTask(t);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleScan(barcode: string) {
    setError(null);
    setMessage(null);
    try {
      const res = await scanPicking(id, {
        barcode,
        quantity: quantity || 1,
        location_id: currentLine?.suggested_location_id,
      });

      // Over-scan and wrong-code are both rejected by the backend; distinguish by feedback.
      let tone: 'success' | 'warning' | 'error';
      if (res.status === 'ok') {
        tone = 'success';
      } else if (res.feedback === 'warning') {
        tone = 'warning'; // over-scan: line already complete / exceeds the order
      } else {
        tone = 'error'; // code not part of this order
      }
      setFeedback(tone);
      showMessage(res.message ?? (res.status === 'ok' ? 'Código correcto' : 'Escaneo no válido'), tone);

      // Refresh task to get authoritative quantities.
      const refreshed =
        res.task && typeof res.task === 'object'
          ? (res.task as PickingTask)
          : await getPickingTask(id);
      setTask(refreshed);
    } catch (err) {
      setFeedback('error');
      setError(errorMessage(err));
    } finally {
      // reset the banner after a moment (the message box keeps its colour)
      setTimeout(() => setFeedback('idle'), 2200);
    }
  }

  // Manually pick the focused line without a scanner. Respects the "cantidad por
  // escaneo" field (capped at what's left), so you can pick a chosen amount.
  async function pickWithoutScanner() {
    if (!currentLine) return;
    const bc = currentLine.barcode_expected?.[0];
    const remaining = currentLine.quantity_required - currentLine.quantity_picked;
    if (!bc || remaining <= 0) return;
    const qty = Math.min(quantity || 1, remaining);
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      if (task && (task.status === 'pending' || task.status === 'assigned')) {
        await startPicking(id);
      }
      const res = await scanPicking(id, {
        barcode: bc,
        quantity: qty,
        location_id: currentLine.suggested_location_id,
      });
      const refreshed =
        res.task && typeof res.task === 'object'
          ? (res.task as PickingTask)
          : await getPickingTask(id);
      setTask(refreshed);
      setFeedback('success');
      showMessage('Línea confirmada', 'success');
      setTimeout(() => setFeedback('idle'), 1200);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  // Undo a line so it can be scanned again (fix a mistake).
  async function resetLine(sku: string) {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const t = await resetPickingLine(id, { sku });
      setTask(t);
      showMessage(`Línea ${sku} reiniciada — vuelva a escanearla`, 'info');
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function submitMissing() {
    if (!missingFor || !missingReason.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const t = await markMissing(id, { sku: missingFor.sku, reason: missingReason.trim() });
      setTask(t);
      setMissingFor(null);
      setMissingReason('');
      showMessage(`Marcado como faltante: ${missingFor.sku}`, 'warning');
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleComplete(allowPartial = false) {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const t = await completePicking(id, allowPartial);
      setTask(t);
      showMessage('Picking completado. Continúe en Packing.', 'success');
      setTimeout(() => navigate('/my/packing'), 900);
    } catch (err) {
      const ax = err as { response?: { status?: number } };
      if (ax.response?.status === 409) {
        setError('Hay líneas pendientes. Puede completar parcialmente.');
      } else {
        setError(errorMessage(err));
      }
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <Loading />;
  if (error && !task) return <ErrorBox message={error} onRetry={load} />;
  if (!task) return null;

  const notStarted = task.status === 'pending' || task.status === 'assigned';
  const hasPending = task.lines.some(
    (l) => l.quantity_picked < l.quantity_required && l.status !== 'missing'
  );

  return (
    <div className="mx-auto max-w-xl pb-24">
      <div className="mb-4 flex items-center justify-between">
        <button onClick={() => navigate('/my/picking')} className="text-sm text-slate-500 underline">
          ‹ Volver
        </button>
        <StatusBadge status={task.status} />
      </div>

      <h1 className="text-2xl font-bold">{task.erp_order_number ?? `Pedido ${task.order_id}`}</h1>
      <div className="mt-1 mb-4 text-sm text-slate-500">
        Progreso: {progress.done}/{progress.lines} líneas · {progress.picked}/{progress.total} unidades
      </div>
      <div className="mb-4 h-3 w-full overflow-hidden rounded-full bg-slate-200">
        <div
          className="h-full bg-emerald-500 transition-all"
          style={{ width: `${progress.total ? (progress.picked / progress.total) * 100 : 0}%` }}
        />
      </div>

      {notStarted && (
        <button onClick={handleStart} className="btn-xl mb-4 w-full bg-brand text-white" disabled={busy}>
          Iniciar picking
        </button>
      )}

      <Toast message={message} tone={messageTone} onClose={() => setMessage(null)} />
      {error && <ErrorBox message={error} />}

      {/* Current line */}
      {currentLine ? (
        <div className="card mb-4 border-2 border-brand">
          <div className="text-xs uppercase tracking-wide text-slate-400">Línea actual</div>
          <div className="text-xl font-bold">{currentLine.name}</div>
          <div className="font-mono text-sm text-slate-500">SKU: {currentLine.sku}</div>
          <div className="mt-2 flex items-center justify-between">
            <span className="text-3xl font-bold">
              {currentLine.quantity_picked}
              <span className="text-lg text-slate-400"> / {currentLine.quantity_required}</span>
            </span>
            <span className="text-sm text-slate-500">
              {currentLine.barcode_expected?.length
                ? `Espera: ${currentLine.barcode_expected.join(', ')}`
                : ''}
            </span>
          </div>
          <div className="mt-1 text-sm font-medium text-amber-700">
            Faltan {Math.max(currentLine.quantity_required - currentLine.quantity_picked, 0)}
          </div>
          <button
            onClick={pickWithoutScanner}
            className="btn mt-3 w-full bg-brand text-white"
            disabled={busy}
          >
            Confirmar sin escáner (+
            {Math.min(quantity, currentLine.quantity_required - currentLine.quantity_picked)})
          </button>
        </div>
      ) : (
        <div className="card mb-4 border-2 border-emerald-400 bg-emerald-50 text-center font-semibold text-emerald-700">
          Todas las líneas resueltas
        </div>
      )}

      {/* Quantity + scanner */}
      {!notStarted && (
        <div className="card mb-4 space-y-3">
          <div className="flex items-center gap-3">
            <label className="label mb-0">Cantidad por escaneo</label>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setQuantity((q) => Math.max(1, q - 1))}
                className="btn-secondary h-12 w-12 text-xl"
              >
                −
              </button>
              <span className="w-12 text-center text-2xl font-bold">{quantity}</span>
              <button
                type="button"
                onClick={() => setQuantity((q) => q + 1)}
                className="btn-secondary h-12 w-12 text-xl"
              >
                +
              </button>
            </div>
          </div>

          <BarcodeScanner onScan={handleScan} feedback={feedback} hint="Escanee el producto de la línea actual" />

          {currentLine && (
            <button
              onClick={() => {
                setMissingFor(currentLine);
                setMissingReason('');
              }}
              className="btn-danger w-full"
            >
              Marcar faltante
            </button>
          )}
        </div>
      )}

      {/* All lines */}
      <div className="card mb-4">
        <h2 className="mb-1 font-semibold">Líneas</h2>
        {!notStarted && hasPending && (
          <p className="mb-2 text-xs text-slate-400">Toca una línea para pickearla.</p>
        )}
        <div className="space-y-2">
          {task.lines.map((l) => {
            const complete = l.quantity_picked >= l.quantity_required;
            const missing = l.status === 'missing';
            const isCurrent = !complete && !missing && currentLine?.sku === l.sku;
            const selectable = !complete && !missing && !notStarted;
            return (
              <div
                key={l.sku}
                onClick={selectable ? () => setSelectedSku(l.sku) : undefined}
                className={`flex items-center justify-between rounded-md border px-3 py-2 ${
                  missing
                    ? 'border-red-300 bg-red-50'
                    : complete
                    ? 'border-emerald-300 bg-emerald-50'
                    : isCurrent
                    ? 'border-brand ring-1 ring-brand'
                    : 'border-slate-200'
                } ${selectable ? 'cursor-pointer' : ''}`}
              >
                <div>
                  <div className="font-medium">
                    {l.name}
                    {isCurrent && (
                      <span className="badge ml-2 bg-blue-100 text-blue-800">pickeando</span>
                    )}
                  </div>
                  <div className="font-mono text-xs text-slate-500">{l.sku}</div>
                </div>
                <div className="text-right">
                  <div className="font-bold">
                    {l.quantity_picked}/{l.quantity_required}
                  </div>
                  {missing && <div className="text-xs text-red-600">faltante</div>}
                  {(l.quantity_picked > 0 || missing) && !notStarted && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        resetLine(l.sku);
                      }}
                      className="mt-1 text-xs font-medium text-brand underline disabled:opacity-50"
                      disabled={busy}
                    >
                      Volver a escanear
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Complete */}
      {!notStarted && (
        <div className="space-y-2">
          <button
            onClick={() => handleComplete(false)}
            className="btn-xl w-full bg-emerald-600 text-white"
            disabled={busy}
          >
            Completar picking
          </button>
          {hasPending && (
            <button
              onClick={() => handleComplete(true)}
              className="btn w-full bg-amber-500 text-white hover:bg-amber-600"
              disabled={busy}
            >
              Completar parcial (con pendientes)
            </button>
          )}
        </div>
      )}

      {/* Missing modal */}
      {missingFor && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-sm rounded-lg bg-white p-4">
            <h3 className="text-lg font-bold">Marcar faltante</h3>
            <p className="mb-3 text-sm text-slate-500">
              {missingFor.name} ({missingFor.sku})
            </p>
            <label className="label">Motivo (obligatorio)</label>
            <textarea
              value={missingReason}
              onChange={(e) => setMissingReason(e.target.value)}
              className="input mb-3 h-24"
              placeholder="Ej: sin stock en ubicación, producto dañado…"
            />
            <div className="flex gap-2">
              <button
                onClick={submitMissing}
                className="btn-danger flex-1"
                disabled={!missingReason.trim() || busy}
              >
                Confirmar faltante
              </button>
              <button onClick={() => setMissingFor(null)} className="btn-secondary flex-1">
                Cancelar
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
