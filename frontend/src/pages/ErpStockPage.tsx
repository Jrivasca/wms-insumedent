import { useEffect, useState } from 'react';
import { getStockComparison, syncStock } from '../api/integrations';
import { errorMessage } from '../api/http';
import { Empty, ErrorBox, Loading, PageHeader } from '../components/Async';
import Pager from '../components/Pager';
import type { ErpStockComparison, ErpStockRow } from '../types';

const PAGE = 50;

function fmt(value: number | null | undefined): string {
  if (value == null) return '—';
  return Number.isInteger(value) ? String(value) : value.toFixed(2);
}

function LotsCell({ row }: { row: ErpStockRow }) {
  if (!row.erp_lots.length) return <span className="text-slate-300">—</span>;
  const shown = row.erp_lots.slice(0, 3);
  return (
    <span className="text-xs text-slate-600">
      {shown
        .map((l) => {
          const exp = l.expiration_date ? new Date(l.expiration_date).toLocaleDateString() : 's/v';
          return `${l.lot_number} (${fmt(l.stock)}, ${exp})`;
        })
        .join(' · ')}
      {row.erp_lots.length > shown.length && ` · +${row.erp_lots.length - shown.length}`}
    </span>
  );
}

/** Stock de Defontana vs stock del WMS. Solo informativo: no modifica ningún saldo. */
export default function ErpStockPage() {
  const [data, setData] = useState<ErpStockComparison | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [onlyDiff, setOnlyDiff] = useState(true);
  const [query, setQuery] = useState('');
  const [offset, setOffset] = useState(0);

  async function load(off = 0, only = onlyDiff, q = query) {
    setLoading(true);
    setError(null);
    try {
      setData(await getStockComparison({ only_diff: only, q: q.trim() || undefined, limit: PAGE, offset: off }));
      setOffset(off);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleSync() {
    setSyncing(true);
    setError(null);
    setNotice(null);
    try {
      const res = await syncStock();
      setNotice(`Stock de Defontana actualizado: ${res.summary?.products ?? 0} productos.`);
      await load(0);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSyncing(false);
    }
  }

  function applyFilters(e: React.FormEvent) {
    e.preventDefault();
    load(0);
  }

  const summary = data?.summary;
  const rows = data?.items ?? [];

  return (
    <div>
      <PageHeader
        title="Inventario · Stock ERP vs WMS"
        subtitle="Compara el stock de Defontana con el del WMS. Es informativo: no modifica ningún saldo."
        actions={
          <button onClick={handleSync} className="btn-primary" disabled={syncing}>
            {syncing ? 'Trayendo…' : 'Traer stock de Defontana'}
          </button>
        }
      />

      {notice && (
        <div className="mb-3 rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-700">{notice}</div>
      )}
      {error && <ErrorBox message={error} />}

      {summary && (
        <div className="card mb-4">
          {summary.snapshot_at ? (
            <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
              <span className="text-slate-500">
                Foto de Defontana: {new Date(summary.snapshot_at).toLocaleString()}
              </span>
              <span>
                <b className="text-orange-700">{summary.with_difference}</b> con diferencia
              </span>
              <span>
                <b>{summary.erp_only}</b> con stock solo en Defontana
              </span>
              <span>
                <b>{summary.wms_only}</b> con stock solo en el WMS
              </span>
            </div>
          ) : (
            <p className="text-sm text-slate-500">
              Aún no hay stock de Defontana. Usa «Traer stock de Defontana» para compararlo.
            </p>
          )}
          {summary.unknown_storage_codes.length > 0 && (
            <p className="mt-2 rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-800">
              Estas bodegas del WMS tienen un código que no existe en Defontana, así que su stock
              aparece separado del de Defontana: {summary.unknown_storage_codes.join(', ')}.
              Corrige el código en Bodegas (por ejemplo <code>BODEGACENTRAL</code>).
            </p>
          )}
          {summary.unmapped_warehouses.length > 0 && (
            <p className="mt-2 rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-800">
              Estas bodegas del WMS tienen stock pero no tienen código de bodega de Defontana, así
              que no se comparan: {summary.unmapped_warehouses.join(', ')}. Asígnales el código
              (por ejemplo <code>BODEGACENTRAL</code>) en Bodegas.
            </p>
          )}
        </div>
      )}

      <form onSubmit={applyFilters} className="card mb-4 flex flex-wrap items-end gap-3">
        <div className="min-w-[14rem] flex-1">
          <label className="label">Buscar</label>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="input"
            placeholder="SKU o nombre"
          />
        </div>
        <label className="flex items-center gap-2 pb-2 text-sm">
          <input
            type="checkbox"
            checked={onlyDiff}
            onChange={(e) => {
              setOnlyDiff(e.target.checked);
              load(0, e.target.checked);
            }}
          />
          Solo diferencias
        </label>
        <button type="submit" className="btn-secondary">
          Buscar
        </button>
      </form>

      {loading ? (
        <Loading />
      ) : rows.length === 0 ? (
        <Empty label={onlyDiff ? 'Sin diferencias' : 'Sin datos'} />
      ) : (
        <div className="mb-2 overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="table w-full">
            <thead className="bg-slate-50">
              <tr>
                <th>SKU</th>
                <th>Producto</th>
                <th>Bodega</th>
                <th className="text-right">Defontana</th>
                <th className="text-right">Reservado</th>
                <th className="text-right">Por recibir</th>
                <th className="text-right">WMS</th>
                <th className="text-right">Diferencia</th>
                <th>Lotes en Defontana</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map((r) => {
                const diffClass =
                  r.difference > 0 ? 'text-emerald-700' : r.difference < 0 ? 'text-red-700' : 'text-slate-400';
                return (
                  <tr key={`${r.sku}|${r.storage_code}`}>
                    <td className="font-mono text-xs">{r.sku}</td>
                    <td>
                      {r.name ?? '—'}
                      {!r.in_wms_catalog && (
                        <span className="ml-1 badge bg-slate-100 text-slate-500">no está en el WMS</span>
                      )}
                      {!r.in_erp && (
                        <span className="ml-1 badge bg-slate-100 text-slate-500">no está en Defontana</span>
                      )}
                    </td>
                    <td className="text-xs">{r.storage_code}</td>
                    <td className="text-right">{fmt(r.erp_stock)}</td>
                    <td className="text-right text-slate-500">{fmt(r.erp_reserved)}</td>
                    <td className="text-right text-slate-500">{fmt(r.erp_to_receive)}</td>
                    <td className="text-right">{fmt(r.wms_stock)}</td>
                    <td className={`text-right font-semibold ${diffClass}`}>
                      {r.difference > 0 ? '+' : ''}
                      {fmt(r.difference)}
                    </td>
                    <td>
                      <LotsCell row={r} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="mb-2 text-xs text-slate-400">
        Diferencia = WMS − Defontana. Positiva: el WMS tiene más unidades; negativa: tiene menos.
      </p>
      <Pager
        offset={offset}
        pageSize={PAGE}
        count={rows.length}
        total={data?.total}
        onPrev={() => load(Math.max(0, offset - PAGE))}
        onNext={() => load(offset + PAGE)}
      />
    </div>
  );
}
