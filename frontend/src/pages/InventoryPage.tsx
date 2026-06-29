import { useEffect, useState } from 'react';
import {
  createAdjustment,
  createTransfer,
  listBalances,
  listMovements,
} from '../api/inventory';
import { listWarehouses, listLocations } from '../api/warehouses';
import { errorMessage } from '../api/http';
import { Empty, ErrorBox, Loading, PageHeader } from '../components/Async';
import type { InventoryBalance, InventoryMovement, Location, Warehouse } from '../types';

export default function InventoryPage() {
  const [balances, setBalances] = useState<InventoryBalance[]>([]);
  const [movements, setMovements] = useState<InventoryMovement[]>([]);
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [locations, setLocations] = useState<Location[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // filters
  const [fProduct, setFProduct] = useState('');
  const [fWarehouse, setFWarehouse] = useState('');
  const [fLocation, setFLocation] = useState('');

  // adjustment form
  const [adj, setAdj] = useState({
    product_id: '',
    warehouse_id: '',
    location_id: '',
    quantity: '',
    reason: '',
    lot_number: '',
    serial_number: '',
  });

  // transfer form
  const [tr, setTr] = useState({
    product_id: '',
    warehouse_id: '',
    from_location_id: '',
    to_location_id: '',
    quantity: '',
  });

  async function loadBalances() {
    setLoading(true);
    setError(null);
    try {
      const data = await listBalances({
        product_id: fProduct.trim() || undefined,
        warehouse_id: fWarehouse.trim() || undefined,
        location_id: fLocation.trim() || undefined,
      });
      setBalances(data);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  async function loadMovements() {
    try {
      setMovements(await listMovements({ product_id: fProduct.trim() || undefined }));
    } catch {
      // movements are secondary; ignore errors silently
    }
  }

  useEffect(() => {
    listWarehouses().then(setWarehouses).catch(() => undefined);
    listLocations().then(setLocations).catch(() => undefined);
    loadBalances();
    loadMovements();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function applyFilters(e: React.FormEvent) {
    e.preventDefault();
    loadBalances();
    loadMovements();
  }

  async function submitAdjustment(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setNotice(null);
    try {
      await createAdjustment({
        product_id: adj.product_id.trim(),
        warehouse_id: adj.warehouse_id.trim(),
        location_id: adj.location_id.trim(),
        quantity: Number(adj.quantity),
        reason: adj.reason.trim(),
        lot_number: adj.lot_number.trim() || undefined,
        serial_number: adj.serial_number.trim() || undefined,
      });
      setNotice('Ajuste registrado');
      setAdj({ ...adj, quantity: '', reason: '', lot_number: '', serial_number: '' });
      loadBalances();
      loadMovements();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function submitTransfer(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setNotice(null);
    try {
      await createTransfer({
        product_id: tr.product_id.trim(),
        warehouse_id: tr.warehouse_id.trim(),
        from_location_id: tr.from_location_id.trim(),
        to_location_id: tr.to_location_id.trim(),
        quantity: Number(tr.quantity),
      });
      setNotice('Transferencia realizada');
      setTr({ ...tr, quantity: '' });
      loadBalances();
      loadMovements();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <div>
      <PageHeader title="Inventario" subtitle="Saldos, movimientos, ajustes y transferencias" />

      {notice && (
        <div className="mb-3 rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-700">{notice}</div>
      )}
      {error && <ErrorBox message={error} />}

      {/* Filters */}
      <form onSubmit={applyFilters} className="card mb-4 grid grid-cols-1 gap-3 md:grid-cols-4">
        <div>
          <label className="label">Product ID</label>
          <input value={fProduct} onChange={(e) => setFProduct(e.target.value)} className="input" placeholder="ID producto" />
        </div>
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

      {/* Balances */}
      <h2 className="mb-2 text-lg font-semibold">Saldos</h2>
      {loading ? (
        <Loading />
      ) : balances.length === 0 ? (
        <Empty label="Sin saldos" />
      ) : (
        <div className="mb-6 overflow-x-auto rounded-lg border border-slate-200 bg-white">
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

      {/* Forms */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <form onSubmit={submitAdjustment} className="card space-y-3">
          <h3 className="font-semibold">Ajuste de inventario</h3>
          <Field label="Product ID" value={adj.product_id} onChange={(v) => setAdj({ ...adj, product_id: v })} required />
          <SelectField
            label="Bodega"
            value={adj.warehouse_id}
            onChange={(v) => setAdj({ ...adj, warehouse_id: v })}
            options={warehouses.map((w) => ({ value: w.id, label: w.name }))}
            required
          />
          <SelectField
            label="Ubicación"
            value={adj.location_id}
            onChange={(v) => setAdj({ ...adj, location_id: v })}
            options={locations.map((l) => ({ value: l.id, label: l.code }))}
            required
          />
          <Field
            label="Cantidad (+/-)"
            type="number"
            value={adj.quantity}
            onChange={(v) => setAdj({ ...adj, quantity: v })}
            required
          />
          <Field label="Motivo" value={adj.reason} onChange={(v) => setAdj({ ...adj, reason: v })} required />
          <div className="grid grid-cols-2 gap-2">
            <Field label="Lote (opc.)" value={adj.lot_number} onChange={(v) => setAdj({ ...adj, lot_number: v })} />
            <Field label="Serie (opc.)" value={adj.serial_number} onChange={(v) => setAdj({ ...adj, serial_number: v })} />
          </div>
          <button type="submit" className="btn-success">
            Registrar ajuste
          </button>
        </form>

        <form onSubmit={submitTransfer} className="card space-y-3">
          <h3 className="font-semibold">Transferencia</h3>
          <Field label="Product ID" value={tr.product_id} onChange={(v) => setTr({ ...tr, product_id: v })} required />
          <SelectField
            label="Bodega"
            value={tr.warehouse_id}
            onChange={(v) => setTr({ ...tr, warehouse_id: v })}
            options={warehouses.map((w) => ({ value: w.id, label: w.name }))}
            required
          />
          <SelectField
            label="Ubicación origen"
            value={tr.from_location_id}
            onChange={(v) => setTr({ ...tr, from_location_id: v })}
            options={locations.map((l) => ({ value: l.id, label: l.code }))}
            required
          />
          <SelectField
            label="Ubicación destino"
            value={tr.to_location_id}
            onChange={(v) => setTr({ ...tr, to_location_id: v })}
            options={locations.map((l) => ({ value: l.id, label: l.code }))}
            required
          />
          <Field
            label="Cantidad"
            type="number"
            value={tr.quantity}
            onChange={(v) => setTr({ ...tr, quantity: v })}
            required
          />
          <button type="submit" className="btn-primary">
            Transferir
          </button>
        </form>
      </div>

      {/* Movements */}
      <h2 className="mb-2 mt-6 text-lg font-semibold">Movimientos recientes</h2>
      {movements.length === 0 ? (
        <Empty label="Sin movimientos" />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
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
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  type = 'text',
  required,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  required?: boolean;
}) {
  return (
    <div>
      <label className="label">{label}</label>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="input"
        required={required}
      />
    </div>
  );
}

function SelectField({
  label,
  value,
  onChange,
  options,
  required,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  required?: boolean;
}) {
  return (
    <div>
      <label className="label">{label}</label>
      <select value={value} onChange={(e) => onChange(e.target.value)} className="input" required={required}>
        <option value="">Seleccione…</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}
