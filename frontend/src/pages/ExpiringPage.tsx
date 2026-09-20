import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { CalendarClock, MoveRight, RotateCcw } from 'lucide-react';
import { listExpiring } from '../api/inventory';
import { listWarehouses } from '../api/warehouses';
import { errorMessage } from '../api/http';
import { Empty, ErrorBox, LoadingRows, PageHeader } from '../components/Async';
import DataTable, { MobileCardList, type Column } from '../components/DataTable';
import LocationCombobox from '../components/LocationCombobox';
import Pager from '../components/Pager';
import SearchInput from '../components/SearchInput';
import type { ExpiringBalance, ExpiringPage as ExpiringPageData, ExpiryBucket, Warehouse } from '../types';

const PAGE = 50;
const HORIZONTES = [30, 90, 180, 365];

const TRAMOS: { key: ExpiryBucket; label: string; classes: string; dot: string }[] = [
  { key: 'expired', label: 'Vencidos', classes: 'bg-red-50 text-red-900', dot: 'bg-red-500' },
  { key: 'd30', label: 'Vencen en 30 días', classes: 'bg-amber-50 text-amber-900', dot: 'bg-amber-500' },
  { key: 'd90', label: '31 a 90 días', classes: 'bg-slate-50 text-slate-700', dot: 'bg-slate-400' },
  { key: 'd180', label: '91 a 180 días', classes: 'bg-slate-50 text-slate-700', dot: 'bg-slate-300' },
];

/** Cuánto queda, en palabras: "vencido hace 3 días", "en 12 días". */
function plazo(dias: number): string {
  if (dias < 0) return `vencido hace ${Math.abs(dias)} d`;
  if (dias === 0) return 'vence hoy';
  return `en ${dias} d`;
}

function TramoBadge({ bucket }: { bucket: ExpiryBucket }) {
  const tramo = TRAMOS.find((t) => t.key === bucket);
  if (!tramo) return null;
  return (
    <span className={`badge ${tramo.classes}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${tramo.dot}`} />
      {tramo.label}
    </span>
  );
}

export default function ExpiringPage() {
  const [data, setData] = useState<ExpiringPageData | null>(null);
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [days, setDays] = useState(180);
  const [fWarehouse, setFWarehouse] = useState('');
  const [fLocation, setFLocation] = useState('');
  const [query, setQuery] = useState('');
  const [offset, setOffset] = useState(0);

  async function load(nextOffset = offset) {
    setLoading(true);
    setError(null);
    try {
      const result = await listExpiring({
        days,
        q: query.trim() || undefined,
        warehouse_id: fWarehouse || undefined,
        location_id: fLocation || undefined,
        limit: PAGE,
        offset: nextOffset,
      });
      setData(result);
      setOffset(nextOffset);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    listWarehouses().then(setWarehouses).catch(() => undefined);
  }, []);

  // Todo lo filtra el servidor; el texto espera a que se deje de escribir.
  useEffect(() => {
    const t = setTimeout(() => load(0), query ? 300 : 0);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [days, fWarehouse, fLocation, query]);

  const items = data?.items ?? [];

  const columns: Column<ExpiringBalance>[] = [
    { key: 'sku', header: 'SKU', render: (b) => <span className="code-strong">{b.sku}</span> },
    {
      key: 'product',
      header: 'Producto',
      render: (b) => <span className="text-slate-700">{b.product_name}</span>,
    },
    {
      key: 'lot',
      header: 'Lote',
      render: (b) => <span className="code">{b.lot_number ?? '—'}</span>,
    },
    {
      key: 'expiry',
      header: 'Vence',
      render: (b) => (
        <span className="whitespace-nowrap">
          {new Date(b.expiration_date).toLocaleDateString('es-CL')}
          <span className="ml-1 text-xs text-slate-500">{plazo(b.days_left)}</span>
        </span>
      ),
    },
    { key: 'bucket', header: 'Tramo', render: (b) => <TramoBadge bucket={b.bucket} /> },
    {
      key: 'location',
      header: 'Ubicación',
      render: (b) => <span className="code">{b.location_code ?? b.location_id}</span>,
    },
    { key: 'on_hand', header: 'En mano', align: 'right', render: (b) => b.quantity_on_hand },
    {
      key: 'available',
      header: 'Disponible',
      align: 'right',
      render: (b) => <span className="font-semibold text-slate-900">{b.quantity_available}</span>,
    },
    {
      key: 'action',
      header: '',
      render: (b) =>
        b.location_type === 'quarantine' ? null : (
          <Link
            to="/inventory/ubicar"
            state={{ balance: b }}
            className="btn-ghost btn-sm whitespace-nowrap"
            title={b.bucket === 'expired' ? 'Mover a cuarentena' : 'Mover a otra ubicación'}
          >
            <MoveRight className="h-4 w-4" aria-hidden="true" />
            {b.bucket === 'expired' ? 'A cuarentena' : 'Mover'}
          </Link>
        ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="Vencimientos"
        subtitle="Stock vencido y por vencer, del más próximo al más lejano"
        actions={
          <button onClick={() => load()} className="btn-secondary">
            <RotateCcw className="h-4 w-4" aria-hidden="true" />
            Refrescar
          </button>
        }
      />

      {error && <ErrorBox message={error} onRetry={() => load()} />}

      <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {TRAMOS.map((tramo) => {
          const bucket = data?.summary.buckets[tramo.key];
          return (
            <div key={tramo.key} className={`card ${tramo.classes}`}>
              <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide">
                <span className={`h-2 w-2 rounded-full ${tramo.dot}`} />
                {tramo.label}
              </p>
              <p className="mt-1 text-2xl font-bold tabular-nums">{bucket?.units ?? 0}</p>
              <p className="text-xs opacity-80">
                unidades · {bucket?.rows ?? 0} {bucket?.rows === 1 ? 'lote' : 'lotes'}
              </p>
            </div>
          );
        })}
      </div>

      <div className="card mb-4 grid gap-3 md:grid-cols-4">
        <div>
          <label className="label" htmlFor="exp-days">
            Horizonte
          </label>
          <select
            id="exp-days"
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="input"
          >
            {HORIZONTES.map((d) => (
              <option key={d} value={d}>
                Próximos {d} días
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="exp-warehouse">
            Bodega
          </label>
          <select
            id="exp-warehouse"
            value={fWarehouse}
            onChange={(e) => {
              setFWarehouse(e.target.value);
              setFLocation('');
            }}
            className="input"
          >
            <option value="">Todas las bodegas</option>
            {warehouses.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </select>
        </div>
        <LocationCombobox
          label="Ubicación"
          value={fLocation}
          onChange={setFLocation}
          warehouseId={fWarehouse}
          placeholder="Todas las ubicaciones"
          clearable
        />
        <SearchInput
          label="Buscar"
          value={query}
          onChange={setQuery}
          placeholder="SKU, producto o lote…"
        />
      </div>

      <h2 className="mb-2 flex items-center gap-1.5 text-sm font-semibold uppercase tracking-wide text-slate-500">
        <CalendarClock className="h-4 w-4" aria-hidden="true" />
        {data?.summary.rows ?? 0} lote(s) · {data?.summary.units ?? 0} unidades
      </h2>

      {loading ? (
        <LoadingRows />
      ) : items.length === 0 ? (
        <Empty
          label="Nada por vencer"
          hint={
            query
              ? 'Ningún lote coincide con la búsqueda.'
              : `Ningún lote con stock vence dentro de ${days} días.`
          }
        />
      ) : (
        <>
          <div className="hidden lg:block">
            <DataTable columns={columns} rows={items} keyOf={(b) => b.id} />
          </div>
          <div className="lg:hidden">
            <MobileCardList
              rows={items}
              keyOf={(b) => b.id}
              render={(b) => (
                <div>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="code-strong">{b.sku}</span>
                    <TramoBadge bucket={b.bucket} />
                  </div>
                  <p className="mt-0.5 truncate text-sm text-slate-700">{b.product_name}</p>
                  <p className="mt-1 text-xs text-slate-500">
                    Lote <span className="code">{b.lot_number ?? '—'}</span> · vence{' '}
                    {new Date(b.expiration_date).toLocaleDateString('es-CL')} ({plazo(b.days_left)})
                  </p>
                  <p className="mt-1 text-xs text-slate-500">
                    <span className="code">{b.location_code ?? b.location_id}</span> ·{' '}
                    {b.quantity_available} disponibles de {b.quantity_on_hand}
                  </p>
                </div>
              )}
            />
          </div>
          <div className="mt-3">
            <Pager
              offset={offset}
              pageSize={PAGE}
              count={items.length}
              total={data?.total ?? 0}
              onPrev={() => load(Math.max(0, offset - PAGE))}
              onNext={() => load(offset + PAGE)}
            />
          </div>
        </>
      )}
    </div>
  );
}
