import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Download, Printer, Ruler, X } from 'lucide-react';
import { listProducts } from '../api/products';
import { errorMessage } from '../api/http';
import { Empty, ErrorBox, LoadingRows, PageHeader } from '../components/Async';
import DataTable, { MobileCardList, type Column } from '../components/DataTable';
import EanBarcode from '../components/EanBarcode';
import { LabelRollPreview, LabelRollPrint, type RollCell } from '../components/LabelRollSheet';
import SearchInput from '../components/SearchInput';
import {
  ZEBRA_ZD220_3X_DEFAULT,
  ZEBRA_ZD220_3X_NAME,
  buildZpl,
  checkProfile,
  expandItems,
  fmtMm,
  template,
  toRows,
  widthSlackMm,
  type RollProfile,
} from '../lib/labelRoll';
import type { Product } from '../types';

// 'sheet' y 'thermal' son los formatos de 50×30 mm de siempre (su marcado está calibrado y
// no se toca). 'roll' es el rollo de varias columnas de la Zebra ZD220.
type Mode = 'sheet' | 'thermal' | 'roll';

const MAX_POR_PRODUCTO = 500;
// La vista previa muestra las primeras filas; la impresión, todas.
const FILAS_VISTA_PREVIA = 12;
const ALINEACION = ['IZQUIERDA', 'CENTRO', 'DERECHA'];
// La calibración es de cada impresora y de cada equipo, así que vive en el navegador.
const PERFIL_KEY = 'wms.etiquetas.zd220-3x';

function cargarPerfil(): RollProfile {
  try {
    const raw = localStorage.getItem(PERFIL_KEY);
    if (raw) return { ...ZEBRA_ZD220_3X_DEFAULT, ...JSON.parse(raw) };
  } catch {
    // Sin almacenamiento (ventana privada, bloqueado): se usa el perfil inicial.
  }
  return ZEBRA_ZD220_3X_DEFAULT;
}

function clampQty(n: number): number {
  if (!Number.isFinite(n)) return 1;
  return Math.max(1, Math.min(Math.floor(n), MAX_POR_PRODUCTO));
}

const PERFIL_CAMPOS: { key: keyof RollProfile; label: string; hint?: string; step?: number }[] = [
  { key: 'paperWidthMm', label: 'Ancho del papel (mm)', hint: 'Provisional: medido con regla.' },
  { key: 'labelWidthMm', label: 'Ancho de etiqueta (mm)' },
  { key: 'labelHeightMm', label: 'Alto de etiqueta (mm)' },
  { key: 'columns', label: 'Columnas', step: 1 },
  { key: 'marginLeftMm', label: 'Margen izquierdo (mm)', hint: 'Sin medir.' },
  { key: 'gapXMm', label: 'Separación entre columnas (mm)', hint: 'Sin medir.' },
  { key: 'marginRightMm', label: 'Margen derecho (mm)', hint: 'Sin medir.' },
  {
    key: 'gapYMm',
    label: 'Separación entre filas (mm)',
    hint: 'Solo informativa: el avance lo detecta la impresora.',
  },
  { key: 'offsetXMm', label: 'Ajuste horizontal (mm)', hint: 'Calibración fina; + corre a la derecha.' },
  { key: 'offsetYMm', label: 'Ajuste vertical (mm)', hint: 'Calibración fina; + corre hacia abajo.' },
];

export default function LabelsPage() {
  const [products, setProducts] = useState<Product[]>([]);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // La selección se mantiene entre búsquedas: se guarda el producto completo por id, con
  // su cantidad, para que lo elegido en una búsqueda siga elegido mientras se buscan otros.
  const [selectedMap, setSelectedMap] = useState<Record<string, { product: Product; qty: number }>>(
    {}
  );
  const [copies, setCopies] = useState(1);
  const [mode, setMode] = useState<Mode>('sheet');
  const [perfil, setPerfil] = useState<RollProfile>(cargarPerfil);
  // Qué se manda a imprimir en modo rollo: las etiquetas o la fila de prueba.
  const [trabajo, setTrabajo] = useState<'labels' | 'alignment'>('labels');
  const [imprimir, setImprimir] = useState(0);

  async function load(term?: string) {
    setLoading(true);
    setError(null);
    try {
      setProducts((await listProducts(term?.trim() || undefined)).items);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    try {
      localStorage.setItem(PERFIL_KEY, JSON.stringify(perfil));
    } catch {
      // Sin almacenamiento: la calibración dura lo que la pestaña.
    }
  }, [perfil]);

  // window.print() recién después de que React pintó lo que se va a imprimir.
  useEffect(() => {
    if (imprimir === 0) return;
    const fin = () => setTrabajo('labels');
    window.addEventListener('afterprint', fin, { once: true });
    window.print();
    return () => window.removeEventListener('afterprint', fin);
  }, [imprimir]);

  function toggle(p: Product) {
    setSelectedMap((m) => {
      const next = { ...m };
      if (next[p.id]) delete next[p.id];
      else next[p.id] = { product: p, qty: clampQty(copies) };
      return next;
    });
  }

  function setQty(id: string, value: number) {
    setSelectedMap((m) => (m[id] ? { ...m, [id]: { ...m[id], qty: clampQty(value) } } : m));
  }

  /** Cambiar las copias generales las aplica a todos los seleccionados. */
  function setCopiesAll(value: number) {
    const n = clampQty(value);
    setCopies(n);
    setSelectedMap((m) =>
      Object.fromEntries(Object.entries(m).map(([id, s]) => [id, { ...s, qty: n }]))
    );
  }

  const selected = useMemo(() => Object.values(selectedMap), [selectedMap]);
  const selectedProducts = useMemo(() => selected.map((s) => s.product), [selected]);

  // Un producto sin código de barras imprime una etiqueta en blanco: hay que avisarlo.
  const withoutBarcode = useMemo(
    () => selectedProducts.filter((p) => !p.barcodes?.[0]?.barcode),
    [selectedProducts]
  );

  const labels = useMemo(() => {
    const out: { key: string; sku: string; name: string; barcode: string }[] = [];
    for (const { product: p, qty } of selected) {
      const barcode = p.barcodes?.[0]?.barcode ?? '';
      for (let i = 0; i < qty; i++) {
        out.push({ key: `${p.id}-${i}`, sku: p.sku, name: p.name, barcode });
      }
    }
    return out;
  }, [selected]);

  // --- Rollo de varias columnas ---
  const chequeo = useMemo(() => checkProfile(perfil), [perfil]);
  const plantilla = useMemo(() => template(perfil), [perfil]);
  const rollo = useMemo(
    () =>
      expandItems(
        selected.map(({ product: p, qty }) => ({
          productId: p.id,
          sku: p.sku,
          barcode: p.barcodes?.[0]?.barcode ?? '',
          quantity: qty,
        })),
        plantilla.maxTextChars
      ),
    [selected, plantilla.maxTextChars]
  );
  const filas: RollCell[][] = useMemo(
    () => (chequeo.errors.length ? [] : toRows<RollCell>(rollo.items, perfil.columns)),
    [rollo.items, perfil.columns, chequeo.errors.length]
  );
  const filaPrueba: RollCell[][] = useMemo(
    () => toRows<RollCell>(ALINEACION.slice(0, perfil.columns), perfil.columns),
    [perfil.columns]
  );
  const perfilValido = chequeo.errors.length === 0;

  function setCampo(key: keyof RollProfile, raw: string) {
    const v = raw.trim() === '' ? NaN : Number(raw.replace(',', '.'));
    setPerfil((p) => ({ ...p, [key]: v }));
  }

  function imprimirRollo(que: 'labels' | 'alignment') {
    setTrabajo(que);
    setImprimir((n) => n + 1);
  }

  function descargarZpl(que: 'labels' | 'alignment') {
    const zpl = buildZpl(que === 'labels' ? filas : filaPrueba, perfil);
    const url = URL.createObjectURL(new Blob([zpl], { type: 'text/plain' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = que === 'labels' ? 'etiquetas-zd220.zpl' : 'prueba-alineacion-zd220.zpl';
    a.click();
    URL.revokeObjectURL(url);
  }

  const columns: Column<Product>[] = [
    {
      key: 'check',
      header: '',
      width: '3rem',
      render: (p) => (
        <input
          type="checkbox"
          checked={!!selectedMap[p.id]}
          readOnly
          tabIndex={-1}
          className="h-4 w-4 rounded border-slate-300 text-brand"
          aria-label={`Seleccionar ${p.sku}`}
        />
      ),
    },
    { key: 'sku', header: 'SKU', render: (p) => <span className="code-strong">{p.sku}</span> },
    {
      key: 'name',
      header: 'Producto',
      render: (p) => <span className="text-slate-700">{p.name}</span>,
    },
    {
      key: 'barcode',
      header: 'Código de barras',
      render: (p) =>
        p.barcodes?.[0]?.barcode ? (
          <span className="code">{p.barcodes[0].barcode}</span>
        ) : (
          <span className="text-xs text-amber-800">sin código</span>
        ),
    },
  ];

  const totalRollo = rollo.items.length;
  const filasRollo = Math.ceil(totalRollo / Math.max(perfil.columns || 1, 1));

  return (
    <div>
      <div className="print:hidden">
        <PageHeader title="Etiquetas" subtitle="Imprima los códigos de barra de sus productos" />

        {error && <ErrorBox message={error} onRetry={() => load(search)} />}

        <div className="mb-3 max-w-md">
          <SearchInput
            value={search}
            onChange={setSearch}
            onSubmit={() => load(search)}
            placeholder="Buscar por nombre o SKU…"
            label="Buscar productos"
          />
        </div>

        {/* Seleccionados: se mantienen entre búsquedas, cada uno con su cantidad */}
        {selected.length > 0 && (
          <div className="mb-3 rounded-card border border-slate-200 bg-slate-50 p-3">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <span className="text-sm font-medium text-slate-600">
                Seleccionados ({selected.length})
              </span>
              <button
                onClick={() => setSelectedMap({})}
                className="text-xs font-medium text-brand hover:underline"
              >
                Quitar todos
              </button>
            </div>
            <div className="flex flex-wrap gap-2">
              {selected.map(({ product: p, qty }) => (
                <div
                  key={p.id}
                  className="flex items-center gap-1 rounded-md border border-slate-200 bg-white py-1 pl-2 pr-1"
                >
                  <span className="code-strong text-xs">{p.sku}</span>
                  <input
                    type="number"
                    min={1}
                    max={MAX_POR_PRODUCTO}
                    value={qty}
                    onChange={(e) => setQty(p.id, Number(e.target.value))}
                    className="input h-8 w-16 px-1 py-0 text-right text-sm"
                    aria-label={`Cantidad de etiquetas de ${p.sku}`}
                  />
                  <button
                    onClick={() => toggle(p)}
                    className="rounded p-1 text-slate-500 hover:bg-slate-100"
                    title="Quitar de la selección"
                    aria-label={`Quitar ${p.sku}`}
                  >
                    <X className="h-3 w-3" aria-hidden="true" />
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {withoutBarcode.length > 0 && (
          <div className="mb-3 flex items-start gap-2 rounded-card border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <span>
              {withoutBarcode.length === 1
                ? `${withoutBarcode[0].sku} no tiene código de barras: su etiqueta saldría sin código.`
                : `${withoutBarcode.length} productos seleccionados no tienen código de barras: sus etiquetas saldrían sin código.`}{' '}
              Agréguelo en Productos antes de imprimir.
            </span>
          </div>
        )}

        {/* Controles de impresión */}
        <div className="card mb-4 flex flex-wrap items-end gap-4">
          <div>
            <label className="label" htmlFor="copies">
              Copias por producto
            </label>
            <input
              id="copies"
              type="number"
              min={1}
              max={MAX_POR_PRODUCTO}
              value={copies}
              onChange={(e) => setCopiesAll(Number(e.target.value))}
              className="input w-28"
            />
            <p className="hint">Se aplica a todos; ajuste cada uno arriba.</p>
          </div>
          <div>
            <label className="label" htmlFor="format">
              Formato
            </label>
            <select
              id="format"
              value={mode}
              onChange={(e) => setMode(e.target.value as Mode)}
              className="input"
            >
              <option value="sheet">Varias por hoja (A4 / adhesivas)</option>
              <option value="thermal">Una por página (impresora térmica)</option>
              <option value="roll">{ZEBRA_ZD220_3X_NAME}</option>
            </select>
          </div>
          <div className="ml-auto flex flex-wrap items-center gap-3">
            <span className="text-sm text-slate-500">
              {mode === 'roll'
                ? `${selected.length} productos · ${totalRollo} etiquetas · ${filasRollo} fila${filasRollo === 1 ? '' : 's'}`
                : `${selected.length} productos · ${labels.length} etiquetas`}
            </span>
            {mode === 'roll' ? (
              <>
                <button
                  onClick={() => descargarZpl('labels')}
                  className="btn-secondary"
                  disabled={!perfilValido || totalRollo === 0}
                  title="Para enviar directo a la impresora compartida, sin el diálogo del navegador"
                >
                  <Download className="h-4 w-4" aria-hidden="true" />
                  ZPL
                </button>
                <button
                  onClick={() => imprimirRollo('labels')}
                  className="btn-primary"
                  disabled={!perfilValido || totalRollo === 0}
                >
                  <Printer className="h-4 w-4" aria-hidden="true" />
                  Imprimir
                </button>
              </>
            ) : (
              <button
                onClick={() => window.print()}
                className="btn-primary"
                disabled={labels.length === 0}
              >
                <Printer className="h-4 w-4" aria-hidden="true" />
                Imprimir
              </button>
            )}
          </div>
        </div>

        {mode === 'roll' && (
          <div className="card mb-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
                Perfil {ZEBRA_ZD220_3X_NAME}
              </h2>
              <div className="flex flex-wrap gap-2">
                <button
                  onClick={() => imprimirRollo('alignment')}
                  className="btn-secondary btn-sm"
                  disabled={!perfilValido}
                >
                  <Ruler className="h-4 w-4" aria-hidden="true" />
                  Prueba de alineación
                </button>
                <button
                  onClick={() => descargarZpl('alignment')}
                  className="btn-ghost btn-sm"
                  disabled={!perfilValido}
                >
                  <Download className="h-4 w-4" aria-hidden="true" />
                  Prueba en ZPL
                </button>
                <button
                  onClick={() => setPerfil(ZEBRA_ZD220_3X_DEFAULT)}
                  className="btn-ghost btn-sm"
                >
                  Restablecer
                </button>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
              {PERFIL_CAMPOS.map((f) => (
                <div key={f.key}>
                  <label className="label" htmlFor={`perfil-${f.key}`}>
                    {f.label}
                  </label>
                  <input
                    id={`perfil-${f.key}`}
                    type="number"
                    step={f.step ?? 0.05}
                    value={Number.isFinite(perfil[f.key]) ? perfil[f.key] : ''}
                    onChange={(e) => setCampo(f.key, e.target.value)}
                    className="input font-mono"
                  />
                  {f.hint && <p className="hint">{f.hint}</p>}
                </div>
              ))}
            </div>
            <p className="mt-3 text-sm text-slate-600">
              Suma de márgenes, etiquetas y separaciones:{' '}
              <span className="font-mono">{fmtMm(perfil.paperWidthMm - widthSlackMm(perfil))} mm</span>{' '}
              de <span className="font-mono">{fmtMm(perfil.paperWidthMm)} mm</span>. Contenido de
              cada etiqueta: código EAN-13 de {fmtMm(plantilla.barHeightMm)} mm de alto con sus
              zonas de silencio y el SKU (hasta {plantilla.maxTextChars} caracteres). El nombre no
              cabe en 30 × 10 mm.
            </p>
            {chequeo.errors.map((e) => (
              <p key={e} className="mt-2 flex items-start gap-2 text-sm text-red-700">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                {e}
              </p>
            ))}
            {chequeo.warnings.map((w) => (
              <p key={w} className="mt-2 flex items-start gap-2 text-sm text-amber-800">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                {w}
              </p>
            ))}
            <details className="mt-3 text-sm text-slate-600">
              <summary className="cursor-pointer font-medium text-slate-700">
                Cómo imprimir desde Windows
              </summary>
              <ol className="mt-2 list-decimal space-y-1 pl-5">
                <li>
                  En el controlador «ZDesigner ZD220-203dpi ZPL», defina un papel del ancho del
                  papel × alto de etiqueta (hoy {fmtMm(perfil.paperWidthMm)} ×{' '}
                  {fmtMm(perfil.labelHeightMm)} mm), vertical, etiquetas con espacios, térmica
                  directa y desplazamientos en 0.
                </li>
                <li>
                  En el diálogo del navegador: esa impresora, escala <strong>100 %</strong> (no
                  «Ajustar»), márgenes <strong>Ninguno</strong> y sin encabezados ni pies de
                  página. Cada fila es una página.
                </li>
                <li>
                  Imprima primero la prueba de alineación: cada palabra debe quedar dentro de su
                  etiqueta. Corrija las medidas o el ajuste fino y repita.
                </li>
                <li>
                  «ZPL» descarga un archivo que va directo a la impresora, sin pasar por el
                  navegador. Con la impresora compartida en Windows:{' '}
                  <span className="code">copy /b etiquetas-zd220.zpl \\NOMBRE-PC\ZD220</span>.
                </li>
              </ol>
            </details>
          </div>
        )}

        {mode === 'roll' && rollo.rejected.length > 0 && (
          <div className="mb-3 flex items-start gap-2 rounded-card border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <div>
              <p>No se imprimen en este formato:</p>
              <ul className="list-disc pl-5">
                {rollo.rejected.map((r) => (
                  <li key={r.sku}>
                    <span className="code">{r.sku}</span>: {r.reason}.
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}

        {/* Rollo: vista previa ampliada, junto a los controles (al papel va LabelRollPrint). */}
        {mode === 'roll' && (
          <div className="mb-4">
            <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
              Vista previa (ampliada ×2)
            </h2>
            {!perfilValido ? (
              <p className="text-sm text-slate-500">Corrija el perfil para ver la vista previa.</p>
            ) : filas.length === 0 ? (
              <>
                <p className="mb-2 text-sm text-slate-500">
                  Sin etiquetas seleccionadas: se muestra la fila de la prueba de alineación.
                </p>
                <div className="max-w-full overflow-x-auto">
                  <LabelRollPreview rows={filaPrueba} profile={perfil} />
                </div>
              </>
            ) : (
              <>
                <div className="max-w-full overflow-x-auto">
                  <LabelRollPreview rows={filas.slice(0, FILAS_VISTA_PREVIA)} profile={perfil} />
                </div>
                {filas.length > FILAS_VISTA_PREVIA && (
                  <p className="mt-1 text-sm text-slate-500">
                    … y {filas.length - FILAS_VISTA_PREVIA} filas más (se imprimen todas).
                  </p>
                )}
              </>
            )}
          </div>
        )}
        {/* Selector de productos */}
        {loading ? (
          <LoadingRows />
        ) : products.length === 0 ? (
          <Empty label="No hay productos" hint="Busque por nombre o SKU para elegir qué imprimir." />
        ) : (
          <>
            <div className="hidden lg:block">
              <DataTable
                columns={columns}
                rows={products}
                keyOf={(p) => p.id}
                onRowClick={toggle}
                rowClassName={(p) => (selectedMap[p.id] ? 'bg-brand-soft' : undefined)}
              />
            </div>
            <div className="lg:hidden">
              <MobileCardList
                rows={products}
                keyOf={(p) => p.id}
                render={(p) => (
                  <button
                    type="button"
                    onClick={() => toggle(p)}
                    className="flex min-h-touch w-full items-center gap-3 text-left"
                  >
                    <input
                      type="checkbox"
                      checked={!!selectedMap[p.id]}
                      readOnly
                      tabIndex={-1}
                      className="h-5 w-5 shrink-0 rounded border-slate-300 text-brand"
                      aria-label={`Seleccionar ${p.sku}`}
                    />
                    <span className="min-w-0 flex-1">
                      <span className="code-strong block">{p.sku}</span>
                      <span className="block truncate text-sm text-slate-700">{p.name}</span>
                      {p.barcodes?.[0]?.barcode ? (
                        <span className="code">{p.barcodes[0].barcode}</span>
                      ) : (
                        <span className="text-xs text-amber-800">sin código</span>
                      )}
                    </span>
                  </button>
                )}
              />
            </div>
          </>
        )}
      </div>

      {mode === 'roll' && perfilValido && (
        <LabelRollPrint rows={trabajo === 'alignment' ? filaPrueba : filas} profile={perfil} />
      )}

      {/* Vista previa e impresión: el tamaño está calibrado para etiquetas de 50×30 mm. */}
      {mode !== 'roll' && labels.length > 0 && (
        <>
          <style>{`@media print { @page { margin: 6mm; } }`}</style>
          <h2 className="mb-2 mt-6 text-sm font-semibold uppercase tracking-wide text-slate-500 print:hidden">
            Vista previa
          </h2>
          <div className="flex flex-wrap gap-1">
            {labels.map((l) => (
              <div
                key={l.key}
                className="flex flex-col items-center justify-center overflow-hidden border border-slate-300"
                style={{
                  width: '50mm',
                  height: '30mm',
                  padding: '1.5mm',
                  breakAfter: mode === 'thermal' ? 'page' : 'auto',
                }}
              >
                <div className="w-full truncate text-center text-[8px] font-semibold leading-tight">
                  {l.name}
                </div>
                <EanBarcode value={l.barcode} height={40} module={1.4} />
                <div className="font-mono text-[9px] leading-none">{l.sku}</div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
