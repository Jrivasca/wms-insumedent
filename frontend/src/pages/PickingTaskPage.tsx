import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, ArrowRight, PackageX, RotateCcw } from 'lucide-react';
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
import ProgressBar from '../components/ProgressBar';
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
      showMessage(
        res.message ?? (res.status === 'ok' ? 'Código correcto' : 'Escaneo no válido'),
        tone
      );

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
      showMessage(`Línea ${sku} reiniciada: vuelve a escanearla`, 'info');
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
      showMessage('Picking completado. Continúa en Packing.', 'success');
      setTimeout(() => navigate('/my/packing'), 900);
    } catch (err) {
      const ax = err as { response?: { status?: number } };
      if (ax.response?.status === 409) {
        setError('Hay líneas pendientes. Puedes completar el picking de forma parcial.');
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
  const remainingCurrent = currentLine
    ? Math.max(currentLine.quantity_required - currentLine.quantity_picked, 0)
    : 0;

  return (
    <div className="mx-auto max-w-xl">
      <div className="mb-3 flex items-center justify-between gap-2">
        <button onClick={() => navigate('/my/picking')} className="btn-ghost btn-sm -ml-2">
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          Volver
        </button>
        <StatusBadge status={task.status} withDot />
      </div>

      <h1 className="text-2xl font-bold tracking-tight text-slate-900">
        {task.erp_order_number ?? `Pedido ${task.order_id}`}
      </h1>
      <p className="mt-1 text-sm text-slate-500">
        {progress.done} de {progress.lines} líneas resueltas
      </p>
      <div className="mb-4 mt-2">
        <ProgressBar value={progress.picked} total={progress.total} unit="unidades" />
      </div>

      {notStarted && (
        <button
          onClick={handleStart}
          className="btn-xl mb-4 w-full bg-brand text-white hover:bg-brand-dark"
          disabled={busy}
        >
          Iniciar picking
          <ArrowRight className="h-5 w-5" aria-hidden="true" />
        </button>
      )}

      <Toast message={message} tone={messageTone} onClose={() => setMessage(null)} />
      {error && <ErrorBox message={error} />}

      {/* Línea actual: es lo único que el operario mira mientras escanea, así que va
          en el panel de mayor contraste. */}
      {currentLine ? (
        <div className="panel-dark mb-4 p-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-graphite-400">
            Línea actual
          </p>
          <p className="mt-1 text-xl font-bold leading-tight text-white">{currentLine.name}</p>
          <p className="mt-0.5 font-mono text-sm tracking-tight text-graphite-200">
            SKU {currentLine.sku}
          </p>

          <div className="mt-3 flex flex-wrap items-end justify-between gap-2">
            <span className="text-4xl font-bold tabular-nums text-white">
              {currentLine.quantity_picked}
              <span className="text-xl font-semibold text-graphite-400">
                {' '}
                / {currentLine.quantity_required}
              </span>
            </span>
            <span className="text-sm font-semibold text-amber-300">Faltan {remainingCurrent}</span>
          </div>

          {currentLine.barcode_expected?.length ? (
            <p className="mt-2 font-mono text-xs tracking-tight text-graphite-400">
              Espera: {currentLine.barcode_expected.join(', ')}
            </p>
          ) : (
            <p className="mt-2 text-xs text-amber-300">
              Esta línea no tiene código de barras: confírmala sin escáner.
            </p>
          )}

          <button
            onClick={pickWithoutScanner}
            className="btn-xl mt-4 w-full bg-brand text-white hover:bg-brand-dark"
            disabled={busy}
          >
            Confirmar sin escáner (+
            {Math.min(quantity, remainingCurrent)})
          </button>
        </div>
      ) : (
        <div className="mb-4 rounded-card border border-emerald-200 bg-emerald-50 p-4 text-center font-semibold text-emerald-900">
          Todas las líneas resueltas
        </div>
      )}

      {/* Cantidad + escáner */}
      {!notStarted && (
        <div className="card mb-4 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <label className="label mb-0" htmlFor="qty">
              Cantidad por escaneo
            </label>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setQuantity((q) => Math.max(1, q - 1))}
                className="btn-secondary h-touch w-touch text-xl"
                aria-label="Restar uno"
              >
                −
              </button>
              <span
                id="qty"
                className="w-12 text-center text-2xl font-bold tabular-nums"
                aria-live="polite"
              >
                {quantity}
              </span>
              <button
                type="button"
                onClick={() => setQuantity((q) => q + 1)}
                className="btn-secondary h-touch w-touch text-xl"
                aria-label="Sumar uno"
              >
                +
              </button>
            </div>
          </div>

          <BarcodeScanner
            onScan={handleScan}
            feedback={feedback}
            hint="Escanea el producto de la línea actual"
          />

          {currentLine && (
            <button
              onClick={() => {
                setMissingFor(currentLine);
                setMissingReason('');
              }}
              className="btn-secondary w-full text-red-700"
            >
              <PackageX className="h-4 w-4" aria-hidden="true" />
              Marcar faltante
            </button>
          )}
        </div>
      )}

      {/* Todas las líneas */}
      <div className="card mb-4">
        <h2 className="mb-1 text-sm font-semibold uppercase tracking-wide text-slate-500">
          Líneas
        </h2>
        {!notStarted && hasPending && (
          <p className="mb-2 text-xs text-slate-500">Toca una línea para pickearla.</p>
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
                className={`flex min-h-touch items-center justify-between gap-3 rounded-md border px-3 py-2 ${
                  missing
                    ? 'border-red-300 bg-red-50'
                    : complete
                      ? 'border-emerald-300 bg-emerald-50'
                      : isCurrent
                        ? 'border-brand ring-1 ring-brand'
                        : 'border-slate-200'
                } ${selectable ? 'cursor-pointer' : ''}`}
              >
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-slate-900">{l.name}</span>
                    {isCurrent && (
                      <span className="badge bg-brand-soft text-brand-darker">pickeando</span>
                    )}
                    {missing && <StatusBadge status="missing" />}
                  </div>
                  <span className="code">{l.sku}</span>
                </div>
                <div className="shrink-0 text-right">
                  <div className="font-bold tabular-nums text-slate-900">
                    {l.quantity_picked}/{l.quantity_required}
                  </div>
                  {(l.quantity_picked > 0 || missing) && !notStarted && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        resetLine(l.sku);
                      }}
                      className="mt-1 inline-flex items-center gap-1 text-xs font-medium text-brand hover:underline disabled:opacity-50"
                      disabled={busy}
                    >
                      <RotateCcw className="h-3 w-3" aria-hidden="true" />
                      Volver a escanear
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Cierre de la tarea */}
      {!notStarted && (
        <div className="space-y-2">
          <button
            onClick={() => handleComplete(false)}
            className="btn-xl w-full bg-emerald-600 text-white hover:bg-emerald-700"
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
              Completar parcial (quedan líneas pendientes)
            </button>
          )}
        </div>
      )}

      {/* Marcar faltante: necesita un motivo escrito, por eso no usa ConfirmDialog */}
      {missingFor && (
        <div
          className="fixed inset-0 z-50 flex items-end justify-center bg-graphite-950/50 p-4 sm:items-center"
          role="dialog"
          aria-modal="true"
          aria-labelledby="missing-title"
        >
          <div className="w-full max-w-sm rounded-card bg-white p-5 shadow-raised">
            <h3 id="missing-title" className="text-lg font-bold text-slate-900">
              Marcar faltante
            </h3>
            <p className="mb-3 text-sm text-slate-500">
              {missingFor.name} · <span className="code">{missingFor.sku}</span>
            </p>
            <label className="label" htmlFor="missing-reason">
              Motivo (obligatorio)
            </label>
            <textarea
              id="missing-reason"
              value={missingReason}
              onChange={(e) => setMissingReason(e.target.value)}
              className="input mb-1 h-24"
              placeholder="Ej: sin stock en la ubicación, producto dañado…"
            />
            <p className="hint mb-3">
              El pedido queda incompleto y se avisará cuando llegue stock de esta línea.
            </p>
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button onClick={() => setMissingFor(null)} className="btn-secondary">
                Cancelar
              </button>
              <button
                onClick={submitMissing}
                className="btn-danger"
                disabled={!missingReason.trim() || busy}
              >
                Confirmar faltante
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
