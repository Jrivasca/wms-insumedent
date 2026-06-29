import { useEffect, useState } from 'react';
import { createLocation, listLocations, listWarehouses } from '../api/warehouses';
import { errorMessage } from '../api/http';
import { Empty, ErrorBox, Loading, PageHeader } from '../components/Async';
import type { Location, Warehouse } from '../types';

export default function LocationsPage() {
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [locations, setLocations] = useState<Location[]>([]);
  const [filterWarehouse, setFilterWarehouse] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);

  const [warehouseId, setWarehouseId] = useState('');
  const [code, setCode] = useState('');
  const [name, setName] = useState('');
  const [type, setType] = useState('');
  const [saving, setSaving] = useState(false);

  async function loadLocations(warehouse?: string) {
    setLoading(true);
    setError(null);
    try {
      setLocations(await listLocations(warehouse || undefined));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    listWarehouses()
      .then(setWarehouses)
      .catch((err) => setError(errorMessage(err)));
    loadLocations();
  }, []);

  function warehouseName(id: string): string {
    return warehouses.find((w) => w.id === id)?.name ?? id;
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await createLocation({
        warehouse_id: warehouseId,
        code: code.trim(),
        name: name.trim() || undefined,
        type: type.trim() || undefined,
      });
      setCode('');
      setName('');
      setType('');
      setShowForm(false);
      loadLocations(filterWarehouse);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <PageHeader
        title="Ubicaciones"
        actions={
          <button onClick={() => setShowForm((v) => !v)} className="btn-primary">
            {showForm ? 'Cerrar' : 'Nueva ubicación'}
          </button>
        }
      />

      <div className="mb-4 flex items-end gap-2">
        <div>
          <label className="label">Filtrar por bodega</label>
          <select
            value={filterWarehouse}
            onChange={(e) => {
              setFilterWarehouse(e.target.value);
              loadLocations(e.target.value);
            }}
            className="input"
          >
            <option value="">Todas</option>
            {warehouses.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      {showForm && (
        <form onSubmit={handleCreate} className="card mb-4 grid grid-cols-1 gap-3 md:grid-cols-4">
          <div>
            <label className="label">Bodega</label>
            <select value={warehouseId} onChange={(e) => setWarehouseId(e.target.value)} className="input" required>
              <option value="">Seleccione…</option>
              {warehouses.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="label">Código</label>
            <input value={code} onChange={(e) => setCode(e.target.value)} className="input" required />
          </div>
          <div>
            <label className="label">Nombre</label>
            <input value={name} onChange={(e) => setName(e.target.value)} className="input" />
          </div>
          <div>
            <label className="label">Tipo</label>
            <input value={type} onChange={(e) => setType(e.target.value)} className="input" placeholder="bin / shelf…" />
          </div>
          <div className="md:col-span-4">
            <button type="submit" className="btn-success" disabled={saving}>
              {saving ? 'Guardando…' : 'Crear ubicación'}
            </button>
          </div>
        </form>
      )}

      {error && <ErrorBox message={error} />}

      {loading ? (
        <Loading />
      ) : locations.length === 0 ? (
        <Empty label="No hay ubicaciones" />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="table w-full">
            <thead className="bg-slate-50">
              <tr>
                <th>Código</th>
                <th>Nombre</th>
                <th>Bodega</th>
                <th>Tipo</th>
                <th>Zona / Pasillo / Rack / Nivel / Bin</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {locations.map((l) => (
                <tr key={l.id}>
                  <td className="font-mono text-xs">{l.code}</td>
                  <td>{l.name ?? '—'}</td>
                  <td>{warehouseName(l.warehouse_id)}</td>
                  <td>{l.type ?? '—'}</td>
                  <td className="text-xs text-slate-500">
                    {[l.zone, l.aisle, l.rack, l.level, l.bin].filter(Boolean).join(' / ') || '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
