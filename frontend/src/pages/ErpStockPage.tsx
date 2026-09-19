import { useEffect, useState } from 'react';
import { AlertTriangle, ArrowDownToLine, Check, CheckCheck, GitCompare } from 'lucide-react';
import {
  applyReconciliation,
  getReconciliationPreview,
  getStockComparison,
  syncStock,
} from '../api/integrations';
import { errorMessage } from '../api/http';
import { Empty, ErrorBox, LoadingRows, PageHeader } from '../components/Async';
import ConfirmDialog from '../components/ConfirmDialog';
import DataTable, { MobileCardList, type Column } from '../components/DataTable';
import MetricCard from '../components/MetricCard';
import Pager from '../components/Pager';
import SearchInput from '../components/SearchInput';
import type { ErpStockComparison, ErpStockRow, ReconcilePreview } from '../types';

const PAGE = 50;

type PreviewRow = ReconcilePreview['items'][number];

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

function ActionChips({ row }: { row: PreviewRow }) {
  if (row.blocked) return <span className="text-xs text-amber-900">{row.blocked}</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {row.actions.map((a, i) => (
        <span
          key={i}
          className={`badge ${
            a.type === 'add' ? 'bg-emerald-100 text-emerald-800' : 'bg-red-100 text-red-800'
          }`}
        >
          {a.type === 'add' ? 'Sumar' : 'Descontar'} {fmt(a.quantity)} en {a.location_code ?? '—'}
          {a.lot_number ? ` · lote ${a.lot_number}` : ''}
          {a.expiration_date
            ? ` (vence ${new Date(a.expiration_date).toLocaleDateString('es-CL')})`
            : ''}
        </span>
      ))}
    </span>
  );
}

/**
 * Stock de Defontana vs stock del WMS, y la conciliación que deja el WMS igual al ERP.
 * Defontana manda las cantidades; la conciliación ajusta el WMS y nunca envía nada al ERP.
 */
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
  const [applying, setApplying] = useState(false);
  const [confirmAll, setConfirmAll] = useState(false);
  const [toApprove, setToApprove] = useState<PreviewRow | null>(null);

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
      if (preview) await loadPreview();
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

  /** Sin filas: las diferencias chicas. Con una fila: la aprobación de un supervisor. */
  async function runApply(row?: PreviewRow) {
    setApplying(true);
    setError(null);
    setNotice(null);
    try {
      const res = await applyReconciliation(
        row
          ? { rows: [{ sku: row.sku, storage_code: row.storage_code }], include_review: true }
          : {}
      );
      const parts = [
        `${res.applied} ajuste(s) aplicado(s) (+${fmt(res.units_added)} / −${fmt(res.units_removed)} unidades)`,
      ];
      if (res.pending_review) parts.push(`${res.pending_review} quedan para revisión`);
      if (res.errors.length) {
        parts.push(`${res.errors.length} no se pudieron aplicar (el stock cambió; reintenta)`);
      }
      setNotice(`Conciliación aplicada: ${parts.join(' · ')}. No se envió nada a Defontana.`);
      setConfirmAll(false);
      setToApprove(null);
      await Promise.all([loadPreview(), load(offset)]);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setApplying(false);
    }
  }

  const summary = data?.summary;
  const rows = data?.items ?? [];
  const reviewUnits = preview?.summary.review_units;

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

  const previewColumns: Column<PreviewRow>[] = [
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
    { key: 'actions', header: 'Qué se haría', render: (r) => <ActionChips row={r} /> },
    {
      key: 'review',
      header: '',
      align: 'right',
      render: (r) =>
        r.needs_review ? (
          <div className="flex flex-col items-end gap-1">
            <span className="badge bg-amber-100 text-amber-900">Para revisar</span>
            <button
              onClick={() => setToApprove(r)}
              className="btn-secondary btn-sm"
              disabled={applying}
            >
              <Check className="h-3.5 w-3.5" aria-hidden="true" />
              Aprobar
            </button>
          </div>
        ) : r.blocked ? null : (
          <span className="text-xs text-slate-500">Se aplica sola</span>
        ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="Stock ERP vs WMS"
        subtitle="Defontana manda las cantidades: aquí se comparan y se concilia el WMS con el ERP."
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

      {/* Conciliación: deja el WMS igual a Defontana, sin enviar nada al ERP */}
      <section className="mt-8">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
            Conciliación
          </h2>
          <div className="flex flex-wrap gap-2">
            <button onClick={loadPreview} className="btn-secondary" disabled={previewing}>
              <GitCompare className="h-4 w-4" aria-hidden="true" />
              {previewing ? 'Calculando…' : preview ? 'Recalcular' : 'Calcular conciliación'}
            </button>
            {preview && preview.summary.auto > 0 && (
              <button
                onClick={() => setConfirmAll(true)}
                className="btn-primary"
                disabled={applying}
              >
                <CheckCheck className="h-4 w-4" aria-hidden="true" />
                Aplicar {preview.summary.auto} diferencias chicas
              </button>
            )}
          </div>
        </div>
        <p className="mb-3 text-sm text-slate-600">
          Ajusta el WMS para dejarlo igual a Defontana: lo que falta se suma con los lotes que
          informa el ERP y queda en <span className="code-strong">SIN-UBICAR</span> hasta que
          bodega lo ubique; lo que sobra se descuenta por vencimiento más próximo (FEFO).{' '}
          <b className="text-slate-900">No se envía nada al ERP.</b>
          {reviewUnits != null && (
            <>
              {' '}
              Las diferencias de más de {fmt(reviewUnits)} unidades no se aplican solas: quedan
              para que un supervisor las apruebe una por una.
            </>
          )}
        </p>

        {preview && (
          <>
            <div className="mb-3 grid grid-cols-2 gap-3 lg:grid-cols-4">
              <MetricCard
                label="Se aplican solas"
                value={preview.summary.auto}
                hint={`Hasta ${fmt(preview.summary.review_units)} unidades`}
                tone={preview.summary.auto > 0 ? 'info' : 'neutral'}
              />
              <MetricCard
                label="Para revisar"
                value={preview.summary.to_review}
                hint={`Más de ${fmt(preview.summary.review_units)} unidades`}
                tone={preview.summary.to_review > 0 ? 'warn' : 'neutral'}
              />
              <MetricCard
                label="Sin poder conciliar"
                value={preview.summary.blocked}
                hint="Falta un dato para decidir"
                tone={preview.summary.blocked > 0 ? 'danger' : 'neutral'}
              />
              <MetricCard
                label="Unidades"
                value={`+${fmt(preview.summary.units_to_add)}`}
                hint={`−${fmt(preview.summary.units_to_remove)} a descontar`}
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
                    rowClassName={(r) => (r.needs_review ? 'bg-amber-50/40' : undefined)}
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
                        <div className="mt-1">
                          <ActionChips row={r} />
                        </div>
                        {r.needs_review && (
                          <div className="mt-2 flex flex-wrap items-center gap-2">
                            <span className="badge bg-amber-100 text-amber-900">
                              Para revisar
                            </span>
                            <button
                              onClick={() => setToApprove(r)}
                              className="btn-secondary btn-sm"
                              disabled={applying}
                            >
                              <Check className="h-3.5 w-3.5" aria-hidden="true" />
                              Aprobar
                            </button>
                          </div>
                        )}
                      </div>
                    )}
                  />
                </div>
                <p className="hint mt-2">
                  Mostrando {preview.items.length} de {preview.total} filas por conciliar, de mayor
                  a menor diferencia.
                </p>
              </>
            )}
          </>
        )}
      </section>

      <ConfirmDialog
        open={confirmAll}
        tone="primary"
        title="¿Aplicar la conciliación?"
        message={
          preview
            ? `Se ajustará el stock del WMS en ${preview.summary.auto} producto(s) para dejarlo igual a Defontana. No se envía nada al ERP. Las ${preview.summary.to_review} diferencias grandes quedan para revisión.`
            : ''
        }
        confirmLabel="Aplicar"
        cancelLabel="Volver"
        busy={applying}
        onConfirm={() => runApply()}
        onCancel={() => setConfirmAll(false)}
      />

      <ConfirmDialog
        open={toApprove !== null}
        tone="primary"
        title="¿Aprobar esta diferencia?"
        message={
          toApprove
            ? `${toApprove.sku}: el WMS pasará de ${fmt(toApprove.wms_stock)} a ${fmt(
                toApprove.erp_stock
              )} unidades, igual que Defontana (${toApprove.difference > 0 ? '+' : ''}${fmt(
                toApprove.difference
              )}). No se envía nada al ERP.`
            : ''
        }
        confirmLabel="Aprobar"
        cancelLabel="Volver"
        busy={applying}
        onConfirm={() => toApprove && runApply(toApprove)}
        onCancel={() => setToApprove(null)}
      />
    </div>
  );
}
