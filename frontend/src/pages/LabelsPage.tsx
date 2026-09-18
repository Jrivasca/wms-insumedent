import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Printer, X } from 'lucide-react';
import { listProducts } from '../api/products';
import { errorMessage } from '../api/http';
import { Empty, ErrorBox, LoadingRows, PageHeader } from '../components/Async';
import DataTable, { MobileCardList, type Column } from '../components/DataTable';
import EanBarcode from '../components/EanBarcode';
import SearchInput from '../components/SearchInput';
import type { Product } from '../types';

type Mode = 'sheet' | 'thermal';

export default function LabelsPage() {
  const [products, setProducts] = useState<Product[]>([]);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Selection persists across searches: keep the full product objects by id, so a
  // product chosen in one search stays selected while you look for others.
  const [selectedMap, setSelectedMap] = useState<Record<string, Product>>({});
  const [copies, setCopies] = useState(1);
  const [mode, setMode] = useState<Mode>('sheet');

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

  function toggle(p: Product) {
    setSelectedMap((m) => {
      const next = { ...m };
      if (next[p.id]) delete next[p.id];
      else next[p.id] = p;
      return next;
    });
  }

  const selectedProducts = useMemo(() => Object.values(selectedMap), [selectedMap]);

  // Un producto sin código de barras imprime una etiqueta en blanco: hay que avisarlo.
  const withoutBarcode = useMemo(
    () => selectedProducts.filter((p) => !p.barcodes?.[0]?.barcode),
    [selectedProducts]
  );

  const labels = useMemo(() => {
    const out: { key: string; sku: string; name: string; barcode: string }[] = [];
    const n = Math.max(1, Math.min(copies, 50));
    for (const p of selectedProducts) {
      const barcode = p.barcodes?.[0]?.barcode ?? '';
      for (let i = 0; i < n; i++) {
        out.push({ key: `${p.id}-${i}`, sku: p.sku, name: p.name, barcode });
      }
    }
    return out;
  }, [selectedProducts, copies]);

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

  return (
    <div>
      <div className="print:hidden">
        <PageHeader title="Etiquetas" subtitle="Imprime los códigos de barra de tus productos" />

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

        {/* Seleccionados: se mantienen entre búsquedas */}
        {selectedProducts.length > 0 && (
          <div className="mb-3 rounded-card border border-slate-200 bg-slate-50 p-3">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <span className="text-sm font-medium text-slate-600">
                Seleccionados ({selectedProducts.length})
              </span>
              <button
                onClick={() => setSelectedMap({})}
                className="text-xs font-medium text-brand hover:underline"
              >
                Quitar todos
              </button>
            </div>
            <div className="flex flex-wrap gap-1">
              {selectedProducts.map((p) => (
                <button
                  key={p.id}
                  onClick={() => toggle(p)}
                  className="badge flex items-center gap-1 bg-brand-soft text-brand-darker"
                  title="Quitar de la selección"
                >
                  {p.sku}
                  <X className="h-3 w-3" aria-hidden="true" />
                </button>
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
              Agrégalo en Productos antes de imprimir.
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
              max={50}
              value={copies}
              onChange={(e) => setCopies(Number(e.target.value) || 1)}
              className="input w-28"
            />
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
            </select>
          </div>
          <div className="ml-auto flex flex-wrap items-center gap-3">
            <span className="text-sm text-slate-500">
              {selectedProducts.length} productos · {labels.length} etiquetas
            </span>
            <button
              onClick={() => window.print()}
              className="btn-primary"
              disabled={labels.length === 0}
            >
              <Printer className="h-4 w-4" aria-hidden="true" />
              Imprimir
            </button>
          </div>
        </div>

        {/* Selector de productos */}
        {loading ? (
          <LoadingRows />
        ) : products.length === 0 ? (
          <Empty label="No hay productos" hint="Busca por nombre o SKU para elegir qué imprimir." />
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

      {/* Vista previa e impresión: el tamaño está calibrado para etiquetas de 50×30 mm. */}
      {labels.length > 0 && (
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
