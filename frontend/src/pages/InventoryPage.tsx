import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { ChevronRight, GitCompare, MoveRight, RotateCcw } from 'lucide-react';
import { listBalances, listMovements } from '../api/inventory';
import { listWarehouses } from '../api/warehouses';
import { errorMessage } from '../api/http';
import { Empty, ErrorBox, LoadingRows, PageHeader } from '../components/Async';
import DataTable, { MobileCardList, type Column } from '../components/DataTable';
import LocationCombobox from '../components/LocationCombobox';
import Pager from '../components/Pager';
import SearchInput from '../components/SearchInput';
import { movementLabel } from '../lib/inventory';
import type { InventoryBalance, InventoryMovement, Warehouse } from '../types';

const PAGE = 50;

export default function InventoryPage() {
  const [balances, setBalances] = useState<InventoryBalance[]>([]);
  const [movements, setMovements] = useState<InventoryMovement[]>([]);
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [fWarehouse, setFWarehouse] = useState('');
  const [fLocation, setFLocation] = useState('');
  const [query, setQuery] = useState('');
  const [balOffset, setBalOffset] = useState(0);
  const [balTotal, setBalTotal] = useState(0);
  const [movOffset, setMovOffset] = useState(0);
  const [movTotal, setMovTotal] = useState(0);

  // Cada búsqueda lleva número: si llega tarde la respuesta de una anterior, se descarta.
  // Si no, al escribir rápido puede quedar en pantalla el resultado de una consulta vieja.
  const peticion = useRef(0);

  async function loadBalances(offset: number) {
    const mia = ++peticion.current;
    setLoading(true);
    setError(null);
    try {
      const data = await listBalances({
        warehouse_id: fWarehouse || undefined,
        location_id: fLocation || undefined,
        q: query.trim() || undefined,
        limit: PAGE,
        offset,
      });
      if (mia !== peticion.current) return;
      setBalances(data.items);
      setBalTotal(data.total);
      setBalOffset(offset);
    } catch (err) {
      if (mia === peticion.current) setError(errorMessage(err));
    } finally {
      if (mia === peticion.current) setLoading(false);
    }
  }

  async function loadMovements(offset: number) {
    try {
      const data = await listMovements({ limit: PAGE, offset });
      setMovements(data.items);
      setMovTotal(data.total);
      setMovOffset(offset);
    } catch {
      // Los movimientos son secundarios: si fallan, la pantalla sigue sirviendo.
    }
  }

  useEffect(() => {
    listWarehouses().then(setWarehouses).catch(() => undefined);
    loadMovements(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Todo lo filtra el backend, sobre TODOS los saldos y no solo la página cargada. El texto
  // espera a que el usuario deje de escribir para no disparar una consulta por tecla.
  useEffect(() => {
    const t = setTimeout(() => loadBalances(0), query ? 300 : 0);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fWarehouse, fLocation, query]);

  const balanceColumns: Column<InventoryBalance>[] = [
    { key: 'sku', header: 'SKU', render: (b) => <span className="code-strong">{b.sku}</span> },
    {
      key: 'product',
      header: 'Producto',
      render: (b) => <span className="text-slate-700">{b.product_name}</span>,
    },
    {
      key: 'location',
      header: 'Ubicación',
      render: (b) => <span className="code">{b.location_code ?? b.location_id}</span>,
    },
    {
      key: 'lot',
      header: 'Lote / Serie',
      secondary: true,
      render: (b) => (
        <span className="code">
          {[b.lot_number, b.serial_number].filter(Boolean).join(' / ') || '—'}
        </span>
      ),
    },
    { key: 'on_hand', header: 'En mano', align: 'right', render: (b) => b.quantity_on_hand },
    {
      key: 'reserved',
      header: 'Reservado',
      align: 'right',
      secondary: true,
      render: (b) => b.quantity_reserved,
    },
    {
      key: 'available',
      header: 'Disponible',
      align: 'right',
      render: (b) => <span className="font-semibold text-slate-900">{b.quantity_available}</span>,
    },
    {
      key: 'expiry',
      header: 'Vence',
      secondary: true,
      render: (b) =>
        b.expiration_date ? (
          <span className="whitespace-nowrap text-xs text-slate-500">
            {new Date(b.expiration_date).toLocaleDateString('es-CL')}
          </span>
        ) : (
          '—'
        ),
    },
    {
      key: 'putaway',
      header: '',
      render: (b) =>
        b.quantity_available > 0 ? (
          <Link
            to="/inventory/ubicar"
            state={{ balance: b }}
            className="btn-ghost btn-sm whitespace-nowrap"
          >
            <MoveRight className="h-4 w-4" aria-hidden="true" />
            Ubicar
          </Link>
        ) : null,
    },
    {
      key: 'blocked',
      header: 'Bloqueado',
      align: 'right',
      secondary: true,
      render: (b) =>
        b.quantity_blocked > 0 ? (
          <span className="font-semibold text-amber-900">{b.quantity_blocked}</span>
        ) : (
          0
        ),
    },
  ];

  const movementColumns: Column<InventoryMovement>[] = [
    {
      key: 'date',
      header: 'Fecha',
      render: (m) => (
        <span className="whitespace-nowrap text-xs text-slate-500">
          {new Date(m.created_at).toLocaleString('es-CL')}
        </span>
      ),
    },
    {
      key: 'type',
      header: 'Tipo',
      render: (m) => <span className="text-slate-700">{movementLabel(m.movement_type)}</span>,
    },
    { key: 'sku', header: 'SKU', render: (m) => <span className="code-strong">{m.sku}</span> },
    {
      key: 'route',
      header: 'Origen → Destino',
      secondary: true,
      render: (m) => (
        <span className="code">
          {m.from_location_id ?? '—'} → {m.to_location_id ?? '—'}
        </span>
      ),
    },
    { key: 'qty', header: 'Cantidad', align: 'right', render: (m) => m.quantity },
    {
      key: 'reason',
      header: 'Motivo',
      secondary: true,
      render: (m) => <span className="text-xs text-slate-500">{m.reason ?? '—'}</span>,
    },
  ];

  return (
    <div>
      <PageHeader
        title="Inventario"
        subtitle="Saldos por ubicación y últimos movimientos"
        actions={
          <>
            <Link to="/inventory/ubicar" className="btn-secondary">
              <MoveRight className="h-4 w-4" aria-hidden="true" />
              Ubicar stock
            </Link>
            <Link to="/inventory/erp-stock" className="btn-secondary">
              <GitCompare className="h-4 w-4" aria-hidden="true" />
              Comparar con Defontana
            </Link>
            <button onClick={() => loadBalances(balOffset)} className="btn-secondary">
              <RotateCcw className="h-4 w-4" aria-hidden="true" />
              Refrescar
            </button>
          </>
        }
      />

      {error && <ErrorBox message={error} onRetry={() => loadBalances(balOffset)} />}

      <div className="card mb-4 grid gap-3 md:grid-cols-3">
        <div>
          <label className="label" htmlFor="inv-warehouse">
            Bodega
          </label>
          <select
            id="inv-warehouse"
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
          placeholder="SKU, producto, código de barras, lote o serie…"
        />
      </div>

      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">Saldos</h2>
      {loading ? (
        <LoadingRows />
      ) : balances.length === 0 ? (
        <Empty
          label={query.trim() ? 'Ningún resultado' : 'Sin saldos'}
          hint={
            query.trim()
              ? 'Ningún saldo coincide con la búsqueda.'
              : 'No hay stock registrado con estos filtros.'
          }
        />
      ) : (
        <>
          <div className="hidden lg:block">
            <DataTable columns={balanceColumns} rows={balances} keyOf={(b) => b.id} />
          </div>
          <div className="lg:hidden">
            <MobileCardList
              rows={balances}
              keyOf={(b) => b.id}
              render={(b) => (
                <div>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="code-strong">{b.sku}</span>
                    <span className="text-sm">
                      <span className="font-bold tabular-nums text-slate-900">
                        {b.quantity_available}
                      </span>
                      <span className="text-slate-500"> disponibles</span>
                    </span>
                  </div>
                  <p className="mt-0.5 truncate text-sm text-slate-700">{b.product_name}</p>
                  <p className="mt-1 text-xs text-slate-500">
                    Ubicación <span className="code">{b.location_code ?? b.location_id}</span>
                    {[b.lot_number, b.serial_number].filter(Boolean).length > 0 && (
                      <> · Lote/Serie {[b.lot_number, b.serial_number].filter(Boolean).join(' / ')}</>
                    )}
                  </p>
                  <p className="mt-1 text-xs text-slate-500">
                    En mano {b.quantity_on_hand} · Reservado {b.quantity_reserved}
                    {b.quantity_blocked > 0 && (
                      <span className="font-medium text-amber-900">
                        {' '}
                        · Bloqueado {b.quantity_blocked}
                      </span>
                    )}
                  </p>
                </div>
              )}
            />
          </div>
        </>
      )}

      <div className="mt-3">
        <Pager
          offset={balOffset}
          pageSize={PAGE}
          count={balances.length}
          total={balTotal}
          onPrev={() => loadBalances(Math.max(0, balOffset - PAGE))}
          onNext={() => loadBalances(balOffset + PAGE)}
        />
      </div>

      <h2 className="mb-2 mt-6 text-sm font-semibold uppercase tracking-wide text-slate-500">
        Últimos movimientos
      </h2>
      {movements.length === 0 ? (
        <Empty label="Sin movimientos" hint="Aquí aparece cada entrada, salida y traslado." />
      ) : (
        <>
          <div className="hidden lg:block">
            <DataTable columns={movementColumns} rows={movements} keyOf={(m) => m.id} />
          </div>
          <div className="lg:hidden">
            <MobileCardList
              rows={movements}
              keyOf={(m) => m.id}
              render={(m) => (
                <div>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-sm font-medium text-slate-900">
                      {movementLabel(m.movement_type)}
                    </span>
                    <span className="text-sm font-bold tabular-nums text-slate-900">
                      {m.quantity}
                    </span>
                  </div>
                  <p className="mt-0.5 text-xs text-slate-500">
                    <span className="code">{m.sku}</span> ·{' '}
                    {new Date(m.created_at).toLocaleString('es-CL')}
                  </p>
                  {m.reason && <p className="mt-1 text-xs text-slate-500">{m.reason}</p>}
                </div>
              )}
            />
          </div>
        </>
      )}

      <div className="mt-3">
        <Pager
          offset={movOffset}
          pageSize={PAGE}
          count={movements.length}
          total={movTotal}
          onPrev={() => loadMovements(Math.max(0, movOffset - PAGE))}
          onNext={() => loadMovements(movOffset + PAGE)}
        />
      </div>

      <Link
        to="/inventory/erp-stock"
        className="mt-4 inline-flex items-center gap-1 text-sm font-medium text-brand hover:underline"
      >
        Ver diferencias de stock contra Defontana
        <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
      </Link>
    </div>
  );
}
