import { useEffect, useState } from 'react';
import { listBalances, listMovements } from '../api/inventory';
import { listWarehouses, listLocations } from '../api/warehouses';
import { errorMessage } from '../api/http';
import { Empty, ErrorBox, Loading, PageHeader } from '../components/Async';
import Pager from '../components/Pager';
import type { InventoryBalance, InventoryMovement, Location, Warehouse } from '../types';

const PAGE = 50;

export default function InventoryPage() {
  const [balances, setBalances] = useState<InventoryBalance[]>([]);
  const [movements, setMovements] = useState<InventoryMovement[]>([]);
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [locations, setLocations] = useState<Location[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [fWarehouse, setFWarehouse] = useState('');
  const [fLocation, setFLocation] = useState('');
  const [balOffset, setBalOffset] = useState(0);
  const [movOffset, setMovOffset] = useState(0);

  async function loadBalances(offset: number) {
    setLoading(true);
    setError(null);
    try {
      const data = await listBalances({
        warehouse_id: fWarehouse || undefined,
        location_id: fLocation || undefined,
        limit: PAGE,
        offset,
      });
      setBalances(data);
      setBalOffset(offset);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  async function loadMovements(offset: number) {
    try {
      setMovements(await listMovements({ limit: PAGE, offset }));
      setMovOffset(offset);
    } catch {
      // movements are secondary; ignore errors silently
    }
  }

  useEffect(() => {
    listWarehouses().then(setWarehouses).catch(() => undefined);
    listLocations().then(setLocations).catch(() => undefined);
    loadBalances(0);
    loadMovements(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function applyFilters(e: React.FormEvent) {
    e.preventDefault();
    loadBalances(0);
  }

  return (
    <div>
      <PageHeader title="Inventario · Saldos" subtitle="Saldos y movimientos de stock" />

      {error && <ErrorBox message={error} />}

      <form onSubmit={applyFilters} className="card mb-4 grid grid-cols-1 gap-3 md:grid-cols-3">
        <div>
          <label className="label">Bodega</label>
          <select value={fWarehouse} onChange={(e) => setFWarehouse(e.target.value)} className="input">
            <option value="">Todas</option>
            {warehouses.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label">Ubicación</label>
          <select value={fLocation} onChange={(e) => setFLocation(e.target.value)} className="input">
            <option value="">Todas</option>
            {locations.map((l) => (
              <option key={l.id} value={l.id}>
                {l.code}
              </option>
            ))}
          </select>
        </div>
        <div className="flex items-end">
          <button type="submit" className="btn-primary w-full">
            Filtrar
          </button>
        </div>
      </form>

      <h2 className="mb-2 text-lg font-semibold">Saldos</h2>
      {loading ? (
        <Loading />
      ) : balances.length === 0 ? (
        <Empty label="Sin saldos" />
      ) : (
        <div className="mb-2 overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="table w-full">
            <thead className="bg-slate-50">
              <tr>
                <th>SKU</th>
                <th>Producto</th>
                <th>Ubicación</th>
                <th>Lote/Serie</th>
                <th>En mano</th>
                <th>Reservado</th>
                <th>Disponible</th>
                <th>Bloqueado</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {balances.map((b) => (
                <tr key={b.id}>
                  <td className="font-mono text-xs">{b.sku}</td>
                  <td>{b.product_name}</td>
                  <td>{b.location_code ?? b.location_id}</td>
                  <td className="text-xs text-slate-500">
                    {[b.lot_number, b.serial_number].filter(Boolean).join(' / ') || '—'}
                  </td>
                  <td>{b.quantity_on_hand}</td>
                  <td>{b.quantity_reserved}</td>
                  <td className="font-semibold">{b.quantity_available}</td>
                  <td>{b.quantity_blocked}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Pager
        offset={balOffset}
        pageSize={PAGE}
        count={balances.length}
        onPrev={() => loadBalances(Math.max(0, balOffset - PAGE))}
        onNext={() => loadBalances(balOffset + PAGE)}
      />

      <h2 className="mb-2 mt-6 text-lg font-semibold">Movimientos</h2>
      {movements.length === 0 ? (
        <Empty label="Sin movimientos" />
      ) : (
        <div className="mb-2 overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="table w-full">
            <thead className="bg-slate-50">
              <tr>
                <th>Fecha</th>
                <th>Tipo</th>
                <th>SKU</th>
                <th>Origen</th>
                <th>Destino</th>
                <th>Cantidad</th>
                <th>Motivo</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {movements.map((m) => (
                <tr key={m.id}>
                  <td className="text-xs text-slate-500">{new Date(m.created_at).toLocaleString()}</td>
                  <td>{m.movement_type}</td>
                  <td className="font-mono text-xs">{m.sku}</td>
                  <td className="text-xs">{m.from_location_id ?? '—'}</td>
                  <td className="text-xs">{m.to_location_id ?? '—'}</td>
                  <td>{m.quantity}</td>
                  <td className="text-xs text-slate-500">{m.reason ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Pager
        offset={movOffset}
        pageSize={PAGE}
        count={movements.length}
        onPrev={() => loadMovements(Math.max(0, movOffset - PAGE))}
        onNext={() => loadMovements(movOffset + PAGE)}
      />
    </div>
  );
}
