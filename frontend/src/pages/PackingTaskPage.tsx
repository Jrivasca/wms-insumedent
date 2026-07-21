import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
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
import StatusBadge from '../components/StatusBadge';
import type { PackingLine, PackingTask } from '../types';

export default function PackingTaskPage() {
  const { id = '' } = useParams();
  const navigate = useNavigate();

  const [task, setTask] = useState<PackingTask | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<ScanFeedback>('idle');
  const [quantity, setQuantity] = useState(1);
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
      const pkg = await createPackage(id, packageLabel.trim() ? { label: packageLabel.trim() } : undefined);
      setActivePackage(pkg.package_id);
      setPackageLabel('');
      setMessage(`Bulto creado: ${pkg.label ?? pkg.package_id}`);
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
      if (res.status === 'ok') {
        setFeedback('success');
        setMessage(res.message ?? 'Producto empacado');
      } else {
        setFeedback('error');
        setMessage(res.message ?? 'Código incorrecto');
      }
      const refreshed =
        res.task && typeof res.task === 'object' ? (res.task as PackingTask) : await getPackingTask(id);
      setTask(refreshed);
      if (res.status === 'ok' && refreshed.lines.some((l) => l.quantity_packed >= l.quantity_required)) {
        setFeedback('warning');
      }
    } catch (err) {
      setFeedback('error');
      setError(errorMessage(err));
    } finally {
      setTimeout(() => setFeedback('idle'), 1500);
    }
  }

  // Demo helper: pack the current line in full without a physical scanner.
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
      setMessage('Línea empacada');
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
      setMessage(`Línea ${sku} reiniciada — vuelva a empacarla`);
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
      setMessage('Packing finalizado. Continúe en Despacho.');
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

  return (
    <div className="mx-auto max-w-xl pb-24">
      <div className="mb-4 flex items-center justify-between">
        <button onClick={() => navigate('/my/packing')} className="text-sm text-slate-500 underline">
          ‹ Volver
        </button>
        <StatusBadge status={task.status} />
      </div>

      <h1 className="text-2xl font-bold">Pedido {task.order_id}</h1>
      <div className="mt-1 mb-4 text-sm text-slate-500">
        Progreso: {progress.done}/{progress.lines} líneas · {progress.packed}/{progress.total} unidades ·{' '}
        {task.packages.length} bultos
      </div>
      <div className="mb-4 h-3 w-full overflow-hidden rounded-full bg-slate-200">
        <div
          className="h-full bg-emerald-500 transition-all"
          style={{ width: `${progress.total ? (progress.packed / progress.total) * 100 : 0}%` }}
        />
      </div>

      {notStarted && (
        <button onClick={handleStart} className="btn-xl mb-4 w-full bg-brand text-white" disabled={busy}>
          Iniciar packing
        </button>
      )}

      {message && (
        <div className="mb-3 rounded-md bg-blue-50 px-3 py-2 text-sm text-blue-700">{message}</div>
      )}
      {error && <ErrorBox message={error} />}

      {/* Packages */}
      <div className="card mb-4">
        <h2 className="mb-2 font-semibold">Bultos</h2>
        <div className="mb-3 flex flex-wrap gap-2">
          {task.packages.length === 0 && (
            <span className="text-sm text-slate-400">Aún no hay bultos. Cree uno para comenzar.</span>
          )}
          {task.packages.map((p) => (
            <button
              key={p.package_id}
              onClick={() => setActivePackage(p.package_id)}
              className={`badge cursor-pointer px-3 py-1 ${
                activePackage === p.package_id
                  ? 'bg-brand text-white'
                  : 'bg-slate-100 text-slate-700'
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
          />
          <button onClick={handleCreatePackage} className="btn-primary whitespace-nowrap" disabled={busy || notStarted}>
            + Bulto
          </button>
        </div>
        {task.packages.length > 0 && (
          <button
            onClick={() => navigate(`/my/packing/${id}/labels`)}
            className="btn-secondary mt-3 w-full"
          >
            🏷️ Imprimir etiquetas de bultos
          </button>
        )}
      </div>

      {/* Current line */}
      {currentLine ? (
        <div className="card mb-4 border-2 border-brand">
          <div className="text-xs uppercase tracking-wide text-slate-400">Producto a empacar</div>
          <div className="text-xl font-bold">{currentLine.name}</div>
          <div className="font-mono text-sm text-slate-500">SKU: {currentLine.sku}</div>
          <div className="mt-2 text-3xl font-bold">
            {currentLine.quantity_packed}
            <span className="text-lg text-slate-400"> / {currentLine.quantity_required}</span>
          </div>
          <button
            onClick={packWithoutScanner}
            className="btn mt-3 w-full bg-brand text-white"
            disabled={busy}
          >
            Confirmar línea sin escáner (demo)
          </button>
        </div>
      ) : (
        <div className="card mb-4 border-2 border-emerald-400 bg-emerald-50 text-center font-semibold text-emerald-700">
          Todas las líneas empacadas
        </div>
      )}

      {/* Quantity + scanner */}
      {!notStarted && (
        <div className="card mb-4 space-y-3">
          <div className="flex items-center gap-3">
            <label className="label mb-0">Cantidad por escaneo</label>
            <div className="flex items-center gap-2">
              <button onClick={() => setQuantity((q) => Math.max(1, q - 1))} className="btn-secondary h-12 w-12 text-xl">
                −
              </button>
              <span className="w-12 text-center text-2xl font-bold">{quantity}</span>
              <button onClick={() => setQuantity((q) => q + 1)} className="btn-secondary h-12 w-12 text-xl">
                +
              </button>
            </div>
          </div>
          {!activePackage && (
            <div className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-700">
              Seleccione o cree un bulto antes de escanear.
            </div>
          )}
          <BarcodeScanner
            onScan={handleScan}
            feedback={feedback}
            hint={
              activePackage
                ? `Empacando en bulto ${activePackage}`
                : 'Escanee el producto a empacar'
            }
          />
        </div>
      )}

      {/* Lines */}
      <div className="card mb-4">
        <h2 className="mb-2 font-semibold">Líneas</h2>
        <div className="space-y-2">
          {task.lines.map((l) => {
            const complete = l.quantity_packed >= l.quantity_required;
            return (
              <div
                key={l.sku}
                className={`flex items-center justify-between rounded-md border px-3 py-2 ${
                  complete ? 'border-emerald-300 bg-emerald-50' : 'border-slate-200'
                }`}
              >
                <div>
                  <div className="font-medium">{l.name}</div>
                  <div className="font-mono text-xs text-slate-500">{l.sku}</div>
                </div>
                <div className="text-right">
                  <div className="font-bold">
                    {l.quantity_packed}/{l.quantity_required}
                  </div>
                  {l.quantity_packed > 0 && !notStarted && (
                    <button
                      onClick={() => resetLine(l.sku)}
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

      {!notStarted && (
        <button onClick={handleComplete} className="btn-xl w-full bg-emerald-600 text-white" disabled={busy}>
          Finalizar packing
        </button>
      )}
    </div>
  );
}
