import { useEffect, useMemo, useState } from 'react';
import { listProducts } from '../api/products';
import { errorMessage } from '../api/http';
import { Empty, ErrorBox, Loading, PageHeader } from '../components/Async';
import EanBarcode from '../components/EanBarcode';
import type { Product } from '../types';

type Mode = 'sheet' | 'thermal';

export default function LabelsPage() {
  const [products, setProducts] = useState<Product[]>([]);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [copies, setCopies] = useState(1);
  const [mode, setMode] = useState<Mode>('sheet');

  async function load(term?: string) {
    setLoading(true);
    setError(null);
    try {
      setProducts(await listProducts(term?.trim() || undefined));
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

  function toggle(id: string) {
    setSelected((s) => ({ ...s, [id]: !s[id] }));
  }

  const selectedProducts = useMemo(
    () => products.filter((p) => selected[p.id]),
    [products, selected]
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

  return (
    <div>
      <div className="print:hidden">
        <PageHeader title="Etiquetas" subtitle="Imprime los códigos de barra de tus productos" />

        {error && <ErrorBox message={error} />}

        <form
          onSubmit={(e) => {
            e.preventDefault();
            load(search);
          }}
          className="mb-3 flex gap-2"
        >
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Buscar por nombre o SKU…"
            className="input"
          />
          <button type="submit" className="btn-secondary whitespace-nowrap">
            Buscar
          </button>
        </form>

        {/* Print controls */}
        <div className="card mb-4 flex flex-wrap items-end gap-4">
          <div>
            <label className="label">Copias por producto</label>
            <input
              type="number"
              min={1}
              max={50}
              value={copies}
              onChange={(e) => setCopies(Number(e.target.value) || 1)}
              className="input w-28"
            />
          </div>
          <div>
            <label className="label">Formato</label>
            <select value={mode} onChange={(e) => setMode(e.target.value as Mode)} className="input">
              <option value="sheet">Varias por hoja (A4 / adhesivas)</option>
              <option value="thermal">Una por página (impresora térmica)</option>
            </select>
          </div>
          <div className="ml-auto flex items-center gap-3">
            <span className="text-sm text-slate-500">
              {selectedProducts.length} productos · {labels.length} etiquetas
            </span>
            <button
              onClick={() => window.print()}
              className="btn-primary"
              disabled={labels.length === 0}
            >
              Imprimir
            </button>
          </div>
        </div>

        {/* Product picker */}
        {loading ? (
          <Loading />
        ) : products.length === 0 ? (
          <Empty label="No hay productos" />
        ) : (
          <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
            <table className="table w-full">
              <thead className="bg-slate-50">
                <tr>
                  <th></th>
                  <th>SKU</th>
                  <th>Producto</th>
                  <th>Código de barras</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {products.map((p) => (
                  <tr
                    key={p.id}
                    onClick={() => toggle(p.id)}
                    className={`cursor-pointer ${selected[p.id] ? 'bg-blue-50' : 'hover:bg-slate-50'}`}
                  >
                    <td>
                      <input type="checkbox" checked={!!selected[p.id]} readOnly />
                    </td>
                    <td className="font-mono text-xs">{p.sku}</td>
                    <td>{p.name}</td>
                    <td className="font-mono text-xs text-slate-500">
                      {p.barcodes?.[0]?.barcode ?? 'sin código'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Preview + print area */}
      {labels.length > 0 && (
        <>
          <style>{`@media print { @page { margin: 6mm; } }`}</style>
          <h2 className="mb-2 mt-6 font-semibold print:hidden">Vista previa</h2>
          <div className="flex flex-wrap gap-1">
            {labels.map((l) => (
              <div
                key={l.key}
                className="flex flex-col items-center justify-center overflow-hidden border border-slate-300"
                style={{ width: '50mm', height: '30mm', padding: '1.5mm', breakAfter: mode === 'thermal' ? 'page' : 'auto' }}
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
