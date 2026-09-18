import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { AlertTriangle, ArrowLeft, ArrowRight, Plus, RotateCcw, Tags } from 'lucide-react';
import {
  completePacking,
  createPackage,
  getPackingTask,
  resetPackingLine,
  scanPacking,
  startPacking,
} from '../api/packing';
import { errorMessage } from '../api/http';
import { ErrorBox, Loading } from '../components/Async';
import BarcodeScanner, { ScanFeedback } from '../components/BarcodeScanner';
import ProgressBar from '../components/ProgressBar';
import StatusBadge from '../components/StatusBadge';
import Toast, { ToastTone } from '../components/Toast';
import type { PackingLine, PackingTask } from '../types';

export default function PackingTaskPage() {
  const { id = '' } = useParams();
  const navigate = useNavigate();

  const [task, setTask] = useState<PackingTask | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [messageTone, setMessageTone] = useState<ToastTone>('info');
  const [feedback, setFeedback] = useState<ScanFeedback>('idle');
  const [quantity, setQuantity] = useState(1);

  function showMsg(text: string, tone: ToastTone = 'info') {
    setMessage(text);
    setMessageTone(tone);
  }
  const [activePackage, setActivePackage] = useState<string | null>(null);
  const [packageLabel, setPackageLabel] = useState('');
  const [busy, setBusy] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const t = await getPackingTask(id);
      setTask(t);
      if (!activePackage && t.packages.length > 0) {
        setActivePackage(t.packages[t.packages.length - 1].package_id);
      }
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

  const currentLine = useMemo<PackingLine | null>(() => {
    if (!task) return null;
    return task.lines.find((l) => l.quantity_packed < l.quantity_required) ?? null;
  }, [task]);

  const progress = useMemo(() => {
    if (!task) return { packed: 0, total: 0, lines: 0, done: 0 };
    const total = task.lines.reduce((a, l) => a + l.quantity_required, 0);
    const packed = task.lines.reduce((a, l) => a + l.quantity_packed, 0);
    const done = task.lines.filter((l) => l.quantity_packed >= l.quantity_required).length;
    return { packed, total, lines: task.lines.length, done };
  }, [task]);

  async function handleStart() {
    setBusy(true);
    setError(null);
    try {
      setTask(await startPacking(id));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleCreatePackage() {
    setBusy(true);
    setError(null);
    try {
      const pkg = await createPackage(
        id,
        packageLabel.trim() ? { label: packageLabel.trim() } : undefined
      );
      setActivePackage(pkg.package_id);
      setPackageLabel('');
      showMsg(`Bulto creado: ${pkg.label ?? pkg.package_id}`, 'success');
      load();
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
      const res = await scanPacking(id, {
        barcode,
        quantity: quantity || 1,
        package_id: activePackage ?? undefined,
      });
      let tone: 'success' | 'warning' | 'error';
      if (res.status === 'ok') tone = 'success';
      else if (res.feedback === 'warning') tone = 'warning'; // over-pack: ya completo / excede
      else tone = 'error'; // código ajeno al pedido
      setFeedback(tone);
      showMsg(
        res.message ?? (res.status === 'ok' ? 'Producto empacado' : 'Escaneo no válido'),
        tone
      );
      const refreshed =
        res.task && typeof res.task === 'object'
          ? (res.task as PackingTask)
          : await getPackingTask(id);
      setTask(refreshed);
    } catch (err) {
      setFeedback('error');
      setError(errorMessage(err));
    } finally {
      setTimeout(() => setFeedback('idle'), 1500);
    }
  }

  // Empaca de una vez todo lo que falta de la línea actual, sin escáner físico.
  async function packWithoutScanner() {
    if (!currentLine) return;
    const bc = currentLine.barcode_expected?.[0];
    const remaining = currentLine.quantity_required - currentLine.quantity_packed;
    if (!bc || remaining <= 0) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      if (task && (task.status === 'pending' || task.status === 'assigned')) {
        await startPacking(id);
      }
      let pkg = activePackage;
      if (!pkg) {
        const created = await createPackage(id, undefined);
        pkg = created.package_id;
        setActivePackage(pkg);
      }
      const res = await scanPacking(id, { barcode: bc, quantity: remaining, package_id: pkg });
      const refreshed =
        res.task && typeof res.task === 'object'
          ? (res.task as PackingTask)
          : await getPackingTask(id);
      setTask(refreshed);
      setFeedback('success');
      showMsg('Línea empacada', 'success');
      setTimeout(() => setFeedback('idle'), 1200);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  // Undo a line so it can be packed again (fix a mistake).
  async function resetLine(sku: string) {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const t = await resetPackingLine(id, { sku });
      setTask(t);
      showMsg(`Línea ${sku} reiniciada: vuelve a empacarla`, 'info');
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleComplete() {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const t = await completePacking(id);
      setTask(t);
      showMsg('Packing finalizado. Continúa en Despacho.', 'success');
      setTimeout(() => navigate('/dispatch'), 900);
    } catch (err) {
      const ax = err as { response?: { status?: number } };
      if (ax.response?.status === 409) {
        setError('Hay líneas pendientes por empacar.');
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
  const activeLabel =
    task.packages.find((p) => p.package_id === activePackage)?.label ?? activePackage;
  const remainingCurrent = currentLine
    ? Math.max(currentLine.quantity_required - currentLine.quantity_packed, 0)
    : 0;

  return (
    <div className="mx-auto max-w-xl">
      <div className="mb-3 flex items-center justify-between gap-2">
        <button onClick={() => navigate('/my/packing')} className="btn-ghost btn-sm -ml-2">
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          Volver
        </button>
        <StatusBadge status={task.status} withDot />
      </div>

      <h1 className="text-2xl font-bold tracking-tight text-slate-900">
        {task.erp_order_number ?? `Pedido ${task.order_id}`}
      </h1>
      <p className="mt-1 text-sm text-slate-500">
        {progress.done} de {progress.lines} líneas empacadas · {task.packages.length} bulto(s)
      </p>
      <div className="mb-4 mt-2">
        <ProgressBar value={progress.packed} total={progress.total} unit="unidades" />
      </div>

      {notStarted && (
        <button
          onClick={handleStart}
          className="btn-xl mb-4 w-full bg-brand text-white hover:bg-brand-dark"
          disabled={busy}
        >
          Iniciar packing
          <ArrowRight className="h-5 w-5" aria-hidden="true" />
        </button>
      )}

      <Toast message={message} tone={messageTone} onClose={() => setMessage(null)} />
      {error && <ErrorBox message={error} />}

      {/* Bultos */}
      <div className="card mb-4">
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
          Bultos
        </h2>
        <div className="mb-3 flex flex-wrap gap-2">
          {task.packages.length === 0 && (
            <p className="text-sm text-slate-500">Aún no hay bultos. Crea uno para comenzar.</p>
          )}
          {task.packages.map((p) => (
            <button
              key={p.package_id}
              onClick={() => setActivePackage(p.package_id)}
              aria-pressed={activePackage === p.package_id}
              className={`min-h-touch rounded-md px-3 py-2 text-sm font-medium ${
                activePackage === p.package_id
                  ? 'bg-brand text-white'
                  : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
              }`}
            >
              {p.label ?? p.package_id} ({p.items?.length ?? 0})
            </button>
          ))}
        </div>
        <div className="flex gap-2">
          <input
            value={packageLabel}
            onChange={(e) => setPackageLabel(e.target.value)}
            placeholder="Etiqueta (opcional)"
            className="input"
            aria-label="Etiqueta del nuevo bulto"
          />
          <button
            onClick={handleCreatePackage}
            className="btn-primary whitespace-nowrap"
            disabled={busy || notStarted}
          >
            <Plus className="h-4 w-4" aria-hidden="true" />
            Bulto
          </button>
        </div>
        {task.packages.length > 0 && (
          <button
            onClick={() => navigate(`/my/packing/${id}/labels`)}
            className="btn-secondary mt-3 w-full"
          >
            <Tags className="h-4 w-4" aria-hidden="true" />
            Imprimir etiquetas de bultos
          </button>
        )}
      </div>

      {/* Producto a empacar: el foco del operario mientras escanea. */}
      {currentLine ? (
        <div className="panel-dark mb-4 p-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-graphite-400">
            Producto a empacar
          </p>
          <p className="mt-1 text-xl font-bold leading-tight text-white">{currentLine.name}</p>
          <p className="mt-0.5 font-mono text-sm tracking-tight text-graphite-200">
            SKU {currentLine.sku}
          </p>

          <div className="mt-3 flex flex-wrap items-end justify-between gap-2">
            <span className="text-4xl font-bold tabular-nums text-white">
              {currentLine.quantity_packed}
              <span className="text-xl font-semibold text-graphite-400">
                {' '}
                / {currentLine.quantity_required}
              </span>
            </span>
            <span className="text-sm font-semibold text-amber-300">Faltan {remainingCurrent}</span>
          </div>

          <button
            onClick={packWithoutScanner}
            className="btn-xl mt-4 w-full bg-brand text-white hover:bg-brand-dark"
            disabled={busy}
          >
            Confirmar línea completa sin escáner (+{remainingCurrent})
          </button>
        </div>
      ) : (
        <div className="mb-4 rounded-card border border-emerald-200 bg-emerald-50 p-4 text-center font-semibold text-emerald-900">
          Todas las líneas empacadas
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

          {!activePackage && (
            <div className="flex items-start gap-2 rounded-card border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              Elige o crea un bulto antes de escanear.
            </div>
          )}

          <BarcodeScanner
            onScan={handleScan}
            feedback={feedback}
            hint={
              activePackage ? `Empacando en el bulto ${activeLabel}` : 'Escanea el producto a empacar'
            }
          />
        </div>
      )}

      {/* Líneas */}
      <div className="card mb-4">
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
          Líneas
        </h2>
        <div className="space-y-2">
          {task.lines.map((l) => {
            const complete = l.quantity_packed >= l.quantity_required;
            return (
              <div
                key={l.sku}
                className={`flex min-h-touch items-center justify-between gap-3 rounded-md border px-3 py-2 ${
                  complete ? 'border-emerald-300 bg-emerald-50' : 'border-slate-200'
                }`}
              >
                <div className="min-w-0">
                  <span className="block font-medium text-slate-900">{l.name}</span>
                  <span className="code">{l.sku}</span>
                </div>
                <div className="shrink-0 text-right">
                  <div className="font-bold tabular-nums text-slate-900">
                    {l.quantity_packed}/{l.quantity_required}
                  </div>
                  {l.quantity_packed > 0 && !notStarted && (
                    <button
                      onClick={() => resetLine(l.sku)}
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

      {!notStarted && (
        <button
          onClick={handleComplete}
          className="btn-xl w-full bg-emerald-600 text-white hover:bg-emerald-700"
          disabled={busy}
        >
          Finalizar packing
        </button>
      )}
    </div>
  );
}
