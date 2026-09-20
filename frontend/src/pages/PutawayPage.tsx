import { useEffect, useMemo, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { MoveRight, PackageSearch, RotateCcw, TriangleAlert } from 'lucide-react';
import { listBalances, putawayBalance } from '../api/inventory';
import { listLocations, listWarehouses } from '../api/warehouses';
import { errorMessage } from '../api/http';
import { Empty, ErrorBox, LoadingRows, PageHeader } from '../components/Async';
import BarcodeScanner, { type ScanFeedback } from '../components/BarcodeScanner';
import LocationCombobox from '../components/LocationCombobox';
import Toast from '../components/Toast';
import type { InventoryBalance, Location, Warehouse } from '../types';

const PAGE = 100;
/** De aquí sale el trabajo: la conciliación deja en SIN-UBICAR todo lo que aparece de más en
 *  Defontana, y ahí no se puede pickear hasta que bodega lo guarde en un estante. */
const ORIGEN_POR_DEFECTO = 'SIN-UBICAR';

function vencimiento(balance: InventoryBalance): Date | null {
  return balance.expiration_date ? new Date(balance.expiration_date) : null;
}

function estaVencido(balance: InventoryBalance): boolean {
  const fecha = vencimiento(balance);
  return !!fecha && fecha.getTime() <= Date.now();
}

function detalle(balance: InventoryBalance): string {
  const partes = [balance.lot_number && `Lote ${balance.lot_number}`,
                  balance.serial_number && `Serie ${balance.serial_number}`];
  const fecha = vencimiento(balance);
  if (fecha) partes.push(`Vence ${fecha.toLocaleDateString('es-CL')}`);
  return partes.filter(Boolean).join(' · ') || 'Sin lote ni serie';
}

export default function PutawayPage() {
  const preseleccionado = (useLocation().state as { balance?: InventoryBalance } | null)?.balance;

  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [locations, setLocations] = useState<Location[]>([]);
  const [warehouseId, setWarehouseId] = useState(preseleccionado?.warehouse_id ?? '');
  const [originId, setOriginId] = useState(preseleccionado?.location_id ?? '');
  const [query, setQuery] = useState('');
  const [balances, setBalances] = useState<InventoryBalance[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selected, setSelected] = useState<InventoryBalance | null>(preseleccionado ?? null);
  const [destinationId, setDestinationId] = useState('');
  const [quantity, setQuantity] = useState('');
  const [saving, setSaving] = useState(false);
  const [feedback, setFeedback] = useState<ScanFeedback>('idle');
  const [toast, setToast] = useState<string | null>(null);

  // Bodegas y, dentro de la elegida, la ubicación de origen por defecto.
  useEffect(() => {
    listWarehouses()
      .then((items) => {
        setWarehouses(items);
        if (!warehouseId && items.length > 0) setWarehouseId(items[0].id);
      })
      .catch((err) => setError(errorMessage(err)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!warehouseId) return;
    listLocations(warehouseId)
      .then((items) => {
        setLocations(items);
        if (!originId) {
          const sinUbicar = items.find((l) => l.code === ORIGEN_POR_DEFECTO);
          if (sinUbicar) setOriginId(sinUbicar.id);
        }
      })
      .catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [warehouseId]);

  // Un escaneo y la búsqueda con retardo pueden pedir a la vez: solo la última pinta la
  // lista, si no puede quedar en pantalla el resultado de una consulta anterior.
  const peticion = useRef(0);

  async function load() {
    const mia = ++peticion.current;
    if (!originId) {
      setBalances([]);
      setTotal(0);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await listBalances({
        warehouse_id: warehouseId || undefined,
        location_id: originId,
        q: query.trim() || undefined,
        limit: PAGE,
      });
      if (mia !== peticion.current) return;
      setBalances(data.items);
      setTotal(data.total);
    } catch (err) {
      if (mia === peticion.current) setError(errorMessage(err));
    } finally {
      if (mia === peticion.current) setLoading(false);
    }
  }

  useEffect(() => {
    const t = setTimeout(load, query ? 300 : 0);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [originId, warehouseId, query]);

  const cuarentena = useMemo(
    () => locations.find((l) => l.type === 'quarantine'),
    [locations]
  );
  const origenCodigo = locations.find((l) => l.id === originId)?.code ?? '';
  // Ubicaciones de trabajo: ahí solo llega mercadería por un pedido, así que no se ofrecen
  // como destino (el backend también las rechaza).
  const comprometidas = useMemo(
    () => locations.filter((l) => ['staging', 'packing', 'dispatch'].includes(l.type ?? ''))
      .map((l) => l.id),
    [locations]
  );

  function elegir(balance: InventoryBalance) {
    setSelected(balance);
    setQuantity(String(balance.quantity_available));
    // Lo vencido no va a un estante de picking: se sugiere cuarentena, no se impone.
    setDestinationId(estaVencido(balance) && cuarentena ? cuarentena.id : '');
    setFeedback('idle');
  }

  /** Un escaneo busca; si deja un solo saldo, lo elige solo para no obligar a tocar la pantalla. */
  function escanear(code: string) {
    const mia = ++peticion.current;
    setQuery(code);
    listBalances({
      warehouse_id: warehouseId || undefined,
      location_id: originId,
      q: code,
      limit: PAGE,
    })
      .then((data) => {
        if (mia !== peticion.current) return;
        setBalances(data.items);
        setTotal(data.total);
        if (data.items.length === 1) {
          elegir(data.items[0]);
          setFeedback('success');
        } else {
          setFeedback(data.items.length === 0 ? 'error' : 'warning');
        }
      })
      .catch((err) => {
        if (mia !== peticion.current) return;
        setError(errorMessage(err));
        setFeedback('error');
      });
  }

  async function confirmar() {
    if (!selected || !destinationId) return;
    setSaving(true);
    setError(null);
    try {
      const result = await putawayBalance({
        balance_id: selected.id,
        to_location_id: destinationId,
        quantity: Number(quantity),
      });
      setToast(`${quantity} u de ${selected.sku} → ${result.to_location_code ?? 'destino'}`);
      // Listo el producto: se limpia para seguir con el siguiente sin tocar los filtros.
      setSelected(null);
      setQuantity('');
      setDestinationId('');
      setQuery('');
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  const cantidadValida =
    Number(quantity) > 0 && !!selected && Number(quantity) <= selected.quantity_available;

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader
        title="Ubicar stock"
        subtitle="Guardar en su estante lo que llegó sin ubicación"
        actions={
          <button onClick={load} className="btn-secondary">
            <RotateCcw className="h-4 w-4" aria-hidden="true" />
            Refrescar
          </button>
        }
      />

      {error && <ErrorBox message={error} onRetry={load} />}

      <div className="card mb-4 grid gap-3 md:grid-cols-2">
        {warehouses.length > 1 && (
          <div>
            <label className="label" htmlFor="pa-warehouse">
              Bodega
            </label>
            <select
              id="pa-warehouse"
              value={warehouseId}
              onChange={(e) => {
                setWarehouseId(e.target.value);
                setOriginId('');
                setSelected(null);
              }}
              className="input"
            >
              {warehouses.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </select>
          </div>
        )}
        <LocationCombobox
          label="Desde"
          value={originId}
          onChange={(id) => {
            setOriginId(id);
            setSelected(null);
          }}
          warehouseId={warehouseId}
          requireWarehouse
          hint="Por defecto SIN-UBICAR, donde la conciliación deja el stock nuevo."
        />
      </div>

      <div className="card mb-4">
        <BarcodeScanner
          onScan={escanear}
          feedback={feedback}
          // Con un producto ya elegido el foco es de la ubicación y la cantidad: si el
          // escáner se lo queda, lo que se escribe en esos campos cae en la caja de escaneo.
          autoFocus={!selected}
          hint="Escanea el producto o escribe SKU, nombre, lote o serie"
        />
        {query && (
          <button onClick={() => setQuery('')} className="btn-ghost btn-sm mt-2">
            Ver todo lo pendiente
          </button>
        )}
      </div>

      {selected && (
        <div className="card mb-4 border-l-4 border-l-brand">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0">
              <span className="code-strong text-lg">{selected.sku}</span>
              <p className="truncate text-sm text-slate-700">{selected.product_name}</p>
              <p className="mt-0.5 text-xs text-slate-500">{detalle(selected)}</p>
            </div>
            <span className="text-sm">
              <span className="font-bold tabular-nums text-slate-900">
                {selected.quantity_available}
              </span>
              <span className="text-slate-500"> disponibles</span>
            </span>
          </div>

          {estaVencido(selected) && (
            <p className="mt-3 flex items-start gap-2 rounded-md bg-amber-50 p-2 text-sm text-amber-900">
              <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              Este lote está vencido.
              {cuarentena
                ? ' Se sugiere dejarlo en cuarentena, no en un estante de picking.'
                : ' Esta bodega no tiene ubicación de cuarentena.'}
            </p>
          )}

          <div className="mt-3 grid gap-3 md:grid-cols-2">
            <LocationCombobox
              label="Hacia"
              value={destinationId}
              onChange={setDestinationId}
              warehouseId={warehouseId}
              requireWarehouse
              disabledIds={[selected.location_id, ...comprometidas]}
            />
            <div>
              <label className="label" htmlFor="pa-qty">
                Cantidad
              </label>
              <input
                id="pa-qty"
                type="number"
                inputMode="decimal"
                min={0}
                max={selected.quantity_available}
                value={quantity}
                onChange={(e) => setQuantity(e.target.value)}
                className="input"
              />
            </div>
          </div>

          <div className="mt-3 flex flex-wrap gap-2">
            <button
              onClick={confirmar}
              disabled={!cantidadValida || !destinationId || saving}
              className="btn-xl flex-1 bg-brand text-white hover:bg-brand-dark"
            >
              <MoveRight className="h-5 w-5" aria-hidden="true" />
              {saving ? 'Ubicando…' : 'Confirmar y seguir'}
            </button>
            <button onClick={() => setSelected(null)} className="btn-secondary">
              Cancelar
            </button>
          </div>
        </div>
      )}

      <h2 className="mb-2 flex items-center gap-1.5 text-sm font-semibold uppercase tracking-wide text-slate-500">
        <PackageSearch className="h-4 w-4" aria-hidden="true" />
        Pendiente en {origenCodigo || 'la ubicación'}
        {total > 0 && <span className="font-normal normal-case text-slate-400">({total})</span>}
      </h2>

      {loading ? (
        <LoadingRows rows={4} />
      ) : balances.length === 0 ? (
        <Empty
          label={query ? 'Ningún resultado' : 'Nada pendiente por ubicar'}
          hint={
            query
              ? 'Ese producto no está en esta ubicación.'
              : 'Todo el stock de esta ubicación ya está guardado en su estante.'
          }
        />
      ) : (
        <div className="space-y-2">
          {balances.map((b) => (
            <button
              key={b.id}
              onClick={() => elegir(b)}
              className={`card flex min-h-touch w-full items-center gap-3 text-left active:bg-slate-50 ${
                selected?.id === b.id ? 'ring-2 ring-brand' : ''
              }`}
            >
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="code-strong">{b.sku}</span>
                  {estaVencido(b) && (
                    <span className="badge bg-amber-100 text-amber-900">Vencido</span>
                  )}
                </span>
                <span className="mt-0.5 block truncate text-sm text-slate-700">
                  {b.product_name}
                </span>
                <span className="mt-0.5 block text-xs text-slate-500">{detalle(b)}</span>
              </span>
              <span className="shrink-0 text-right text-sm">
                <span className="block font-bold tabular-nums text-slate-900">
                  {b.quantity_available}
                </span>
                <span className="text-xs text-slate-500">disponibles</span>
              </span>
            </button>
          ))}
          {total > balances.length && (
            <p className="hint">
              Se muestran {balances.length} de {total}. Busca por SKU o escanea para acotar.
            </p>
          )}
        </div>
      )}

      <Toast message={toast} tone="success" onClose={() => setToast(null)} />
    </div>
  );
}
