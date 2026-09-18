import { useEffect, useState } from 'react';
import { AlertTriangle, ArrowDownToLine, CheckCheck, GitCompare } from 'lucide-react';
import { getReconciliationPreview, getStockComparison, syncStock } from '../api/integrations';
import { errorMessage } from '../api/http';
import { Empty, ErrorBox, LoadingRows, PageHeader } from '../components/Async';
import DataTable, { MobileCardList, type Column } from '../components/DataTable';
import MetricCard from '../components/MetricCard';
import Pager from '../components/Pager';
import SearchInput from '../components/SearchInput';
import type { ErpStockComparison, ErpStockRow, ReconcilePreview } from '../types';

const PAGE = 50;

function fmt(value: number | null | undefined): string {
  if (value == null) return '—';
  return Number.isInteger(value) ? String(value) : value.toFixed(2);
}

function diffClass(difference: number): string {
  if (difference > 0) return 'text-emerald-700';
  if (difference < 0) return 'text-red-700';
  return 'text-slate-400';
}

function DiffValue({ difference }: { difference: number }) {
  return (
    <span className={`font-semibold tabular-nums ${diffClass(difference)}`}>
      {difference > 0 ? '+' : ''}
      {fmt(difference)}
    </span>
  );
}

function LotsCell({ row }: { row: ErpStockRow }) {
  if (!row.erp_lots.length) return <span className="text-slate-300">—</span>;
  const shown = row.erp_lots.slice(0, 3);
  return (
    <span className="text-xs text-slate-600">
      {shown
        .map((l) => {
          const exp = l.expiration_date
            ? new Date(l.expiration_date).toLocaleDateString('es-CL')
            : 's/v';
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
  const [preview, setPreview] = useState<ReconcilePreview | null>(null);
  const [previewing, setPreviewing] = useState(false);

  async function load(off = 0, only = onlyDiff, q = query) {
    setLoading(true);
    setError(null);
    try {
      setData(
        await getStockComparison({
          only_diff: only,
          q: q.trim() || undefined,
          limit: PAGE,
          offset: off,
        })
      );
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

  async function loadPreview() {
    setPreviewing(true);
    setError(null);
    try {
      setPreview(await getReconciliationPreview({ q: query.trim() || undefined, limit: 50 }));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setPreviewing(false);
    }
  }

  const summary = data?.summary;
  const rows = data?.items ?? [];

  const columns: Column<ErpStockRow>[] = [
    { key: 'sku', header: 'SKU', render: (r) => <span className="code-strong">{r.sku}</span> },
    {
      key: 'name',
      header: 'Producto',
      render: (r) => (
        <span className="flex flex-wrap items-center gap-1">
          <span className="text-slate-700">{r.name ?? '—'}</span>
          {!r.in_wms_catalog && (
            <span className="badge bg-slate-100 text-slate-600">no está en el WMS</span>
          )}
          {!r.in_erp && (
            <span className="badge bg-slate-100 text-slate-600">no está en Defontana</span>
          )}
        </span>
      ),
    },
    {
      key: 'storage',
      header: 'Bodega',
      render: (r) => <span className="code">{r.storage_code}</span>,
    },
    { key: 'erp', header: 'Defontana', align: 'right', render: (r) => fmt(r.erp_stock) },
    {
      key: 'reserved',
      header: 'Reservado',
      align: 'right',
      secondary: true,
      render: (r) => <span className="text-slate-500">{fmt(r.erp_reserved)}</span>,
    },
    {
      key: 'to_receive',
      header: 'Por recibir',
      align: 'right',
      secondary: true,
      render: (r) => <span className="text-slate-500">{fmt(r.erp_to_receive)}</span>,
    },
    { key: 'wms', header: 'WMS', align: 'right', render: (r) => fmt(r.wms_stock) },
    {
      key: 'diff',
      header: 'Diferencia',
      align: 'right',
      render: (r) => <DiffValue difference={r.difference} />,
    },
    {
      key: 'lots',
      header: 'Lotes en Defontana',
      secondary: true,
      render: (r) => <LotsCell row={r} />,
    },
  ];

  const previewColumns: Column<ReconcilePreview['items'][number]>[] = [
    { key: 'sku', header: 'SKU', render: (r) => <span className="code-strong">{r.sku}</span> },
    {
      key: 'name',
      header: 'Producto',
      render: (r) => <span className="text-slate-700">{r.name ?? '—'}</span>,
    },
    {
      key: 'warehouse',
      header: 'Bodega',
      secondary: true,
      render: (r) => <span className="code">{r.warehouse_name ?? r.storage_code}</span>,
    },
    {
      key: 'diff',
      header: 'Diferencia',
      align: 'right',
      render: (r) => <DiffValue difference={r.difference} />,
    },
    {
      key: 'actions',
      header: 'Qué se haría',
      render: (r) =>
        r.blocked ? (
          <span className="text-xs text-amber-900">{r.blocked}</span>
        ) : (
          <span className="flex flex-wrap gap-1">
            {r.actions.map((a, i) => (
              <span
                key={i}
                className={`badge ${
                  a.type === 'add' ? 'bg-emerald-100 text-emerald-800' : 'bg-red-100 text-red-800'
                }`}
              >
                {a.type === 'add' ? 'Sumar' : 'Descontar'} {fmt(a.quantity)} en{' '}
                {a.location_code ?? '—'}
                {a.lot_number ? ` · lote ${a.lot_number}` : ''}
                {a.expiration_date
                  ? ` (vence ${new Date(a.expiration_date).toLocaleDateString('es-CL')})`
                  : ''}
              </span>
            ))}
          </span>
        ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="Stock ERP vs WMS"
        subtitle="Compara el stock de Defontana con el del WMS. Es informativo: no modifica ningún saldo."
        actions={
          <button onClick={handleSync} className="btn-primary" disabled={syncing}>
            <ArrowDownToLine className="h-4 w-4" aria-hidden="true" />
            {syncing ? 'Trayendo…' : 'Traer stock de Defontana'}
          </button>
        }
      />

      {notice && (
        <div className="mb-3 flex items-start gap-2 rounded-card border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
          <CheckCheck className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          {notice}
        </div>
      )}
      {error && <ErrorBox message={error} onRetry={() => load(offset)} />}

      {summary && !summary.snapshot_at && (
        <div className="card mb-4">
          <p className="text-sm text-slate-600">
            Aún no hay stock de Defontana. Usa «Traer stock de Defontana» para compararlo.
          </p>
        </div>
      )}

      {summary && summary.snapshot_at && (
        <>
          <div className="mb-3 grid grid-cols-2 gap-3 lg:grid-cols-3">
            <MetricCard
              label="Con diferencia"
              value={summary.with_difference}
              hint="WMS y Defontana no coinciden"
              tone={summary.with_difference > 0 ? 'warn' : 'ok'}
              icon={GitCompare}
            />
            <MetricCard
              label="Solo en Defontana"
              value={summary.erp_only}
              hint="Con stock allá, sin stock acá"
            />
            <MetricCard
              label="Solo en el WMS"
              value={summary.wms_only}
              hint="Con stock acá, sin stock allá"
            />
          </div>
          <p className="mb-3 text-xs text-slate-500">
            Foto de Defontana: {new Date(summary.snapshot_at).toLocaleString('es-CL')}
          </p>
        </>
      )}

      {summary && summary.unknown_storage_codes.length > 0 && (
        <div className="mb-3 flex items-start gap-2 rounded-card border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <span>
            Estas bodegas del WMS tienen un código que no existe en Defontana, así que su stock
            aparece separado: {summary.unknown_storage_codes.join(', ')}. Corrige el código en
            Bodegas (por ejemplo <code className="code-strong">BODEGACENTRAL</code>).
          </span>
        </div>
      )}
      {summary && summary.unmapped_warehouses.length > 0 && (
        <div className="mb-3 flex items-start gap-2 rounded-card border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <span>
            Estas bodegas del WMS tienen stock pero no tienen código de bodega de Defontana, así que
            no se comparan: {summary.unmapped_warehouses.join(', ')}. Asígnales el código (por
            ejemplo <code className="code-strong">BODEGACENTRAL</code>) en Bodegas.
          </span>
        </div>
      )}

      <div className="card mb-4 flex flex-wrap items-end gap-4">
        <div className="min-w-[14rem] flex-1">
          <SearchInput
            label="Buscar"
            value={query}
            onChange={setQuery}
            onSubmit={() => load(0)}
            placeholder="SKU o nombre"
          />
          <p className="hint">Esta búsqueda la resuelve el servidor sobre todo el listado.</p>
        </div>
        <label className="flex min-h-touch items-center gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            className="h-4 w-4 rounded border-slate-300 text-brand focus:ring-brand"
            checked={onlyDiff}
            onChange={(e) => {
              setOnlyDiff(e.target.checked);
              load(0, e.target.checked);
            }}
          />
          Solo diferencias
        </label>
      </div>

      {loading ? (
        <LoadingRows />
      ) : rows.length === 0 ? (
        <Empty
          label={onlyDiff ? 'Sin diferencias' : 'Sin datos'}
          hint={
            onlyDiff
              ? 'El stock del WMS coincide con el de Defontana en todo lo comparable.'
              : 'Trae el stock de Defontana para poder comparar.'
          }
        />
      ) : (
        <>
          <div className="hidden lg:block">
            <DataTable
              columns={columns}
              rows={rows}
              keyOf={(r) => `${r.sku}|${r.storage_code}`}
              rowClassName={(r) => (r.difference !== 0 ? 'bg-amber-50/40' : undefined)}
            />
          </div>
          <div className="lg:hidden">
            <MobileCardList
              rows={rows}
              keyOf={(r) => `${r.sku}|${r.storage_code}`}
              render={(r) => (
                <div>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="code-strong">{r.sku}</span>
                    <DiffValue difference={r.difference} />
                  </div>
                  <p className="mt-0.5 truncate text-sm text-slate-700">{r.name ?? '—'}</p>
                  <p className="mt-1 text-xs text-slate-500">
                    Bodega <span className="code">{r.storage_code}</span> · Defontana{' '}
                    {fmt(r.erp_stock)} · WMS {fmt(r.wms_stock)}
                  </p>
                  {r.erp_lots.length > 0 && (
                    <p className="mt-1">
                      <LotsCell row={r} />
                    </p>
                  )}
                </div>
              )}
            />
          </div>

          <p className="hint mt-2">
            Diferencia = WMS − Defontana. Positiva: el WMS tiene más unidades; negativa, menos.
          </p>

          <div className="mt-3">
            <Pager
              offset={offset}
              pageSize={PAGE}
              count={rows.length}
              total={data?.total}
              onPrev={() => load(Math.max(0, offset - PAGE))}
              onNext={() => load(offset + PAGE)}
            />
          </div>
        </>
      )}

      {/* Conciliación: qué habría que ajustar para igualar el WMS a Defontana */}
      <section className="mt-8">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
            Conciliación (vista previa)
          </h2>
          <button onClick={loadPreview} className="btn-secondary" disabled={previewing}>
            <GitCompare className="h-4 w-4" aria-hidden="true" />
            {previewing ? 'Calculando…' : 'Calcular conciliación'}
          </button>
        </div>
        <p className="mb-3 text-sm text-slate-600">
          Muestra qué habría que ajustar en el WMS para dejarlo igual a Defontana: lo que falta se
          sumaría con los lotes que informa el ERP, y lo que sobra se descontaría por vencimiento
          más próximo (FEFO). <b className="text-slate-900">No modifica nada.</b>
        </p>

        {preview && (
          <>
            <div className="mb-3 grid grid-cols-2 gap-3 lg:grid-cols-3">
              <MetricCard
                label="A sumar"
                value={preview.summary.to_add}
                hint={`${preview.summary.units_to_add} unidades`}
                tone="ok"
              />
              <MetricCard
                label="A descontar"
                value={preview.summary.to_remove}
                hint={`${preview.summary.units_to_remove} unidades`}
                tone={preview.summary.to_remove > 0 ? 'danger' : 'neutral'}
              />
              <MetricCard
                label="Sin poder conciliar"
                value={preview.summary.blocked}
                hint="Falta un dato para decidir"
                tone={preview.summary.blocked > 0 ? 'warn' : 'neutral'}
              />
            </div>

            {preview.items.length === 0 ? (
              <Empty
                label="Nada que conciliar"
                hint="El WMS ya coincide con Defontana en lo comparable."
              />
            ) : (
              <>
                <div className="hidden lg:block">
                  <DataTable
                    columns={previewColumns}
                    rows={preview.items}
                    keyOf={(r) => `${r.sku}|${r.storage_code}`}
                  />
                </div>
                <div className="lg:hidden">
                  <MobileCardList
                    rows={preview.items}
                    keyOf={(r) => `${r.sku}|${r.storage_code}`}
                    render={(r) => (
                      <div>
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <span className="code-strong">{r.sku}</span>
                          <DiffValue difference={r.difference} />
                        </div>
                        <p className="mt-0.5 truncate text-sm text-slate-700">{r.name ?? '—'}</p>
                        <p className="mt-1 text-xs text-slate-500">
                          {r.warehouse_name ?? r.storage_code}
                        </p>
                        {r.blocked ? (
                          <p className="mt-1 text-xs text-amber-900">{r.blocked}</p>
                        ) : (
                          <p className="mt-1 flex flex-wrap gap-1">
                            {r.actions.map((a, i) => (
                              <span
                                key={i}
                                className={`badge ${
                                  a.type === 'add'
                                    ? 'bg-emerald-100 text-emerald-800'
                                    : 'bg-red-100 text-red-800'
                                }`}
                              >
                                {a.type === 'add' ? 'Sumar' : 'Descontar'} {fmt(a.quantity)} en{' '}
                                {a.location_code ?? '—'}
                                {a.lot_number ? ` · lote ${a.lot_number}` : ''}
                              </span>
                            ))}
                          </p>
                        )}
                      </div>
                    )}
                  />
                </div>
                <p className="hint mt-2">
                  Mostrando {preview.items.length} de {preview.total} filas por conciliar.
                </p>
              </>
            )}
          </>
        )}
      </section>
    </div>
  );
}
