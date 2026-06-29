import { useEffect, useState } from 'react';
import { createWarehouse, listWarehouses } from '../api/warehouses';
import { errorMessage } from '../api/http';
import { Empty, ErrorBox, Loading, PageHeader } from '../components/Async';
import type { Warehouse } from '../types';

export default function WarehousesPage() {
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);

  const [name, setName] = useState('');
  const [erpCode, setErpCode] = useState('');
  const [type, setType] = useState('');
  const [saving, setSaving] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setWarehouses(await listWarehouses());
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await createWarehouse({
        name: name.trim(),
        erp_storage_code: erpCode.trim() || undefined,
        type: type.trim() || undefined,
      });
      setName('');
      setErpCode('');
      setType('');
      setShowForm(false);
      load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <PageHeader
        title="Bodegas"
        actions={
          <button onClick={() => setShowForm((v) => !v)} className="btn-primary">
            {showForm ? 'Cerrar' : 'Nueva bodega'}
          </button>
        }
      />

      {showForm && (
        <form onSubmit={handleCreate} className="card mb-4 grid grid-cols-1 gap-3 md:grid-cols-3">
          <div>
            <label className="label">Nombre</label>
            <input value={name} onChange={(e) => setName(e.target.value)} className="input" required />
          </div>
          <div>
            <label className="label">Código ERP</label>
            <input value={erpCode} onChange={(e) => setErpCode(e.target.value)} className="input" />
          </div>
          <div>
            <label className="label">Tipo</label>
            <input value={type} onChange={(e) => setType(e.target.value)} className="input" placeholder="main / quarantine…" />
          </div>
          <div className="md:col-span-3">
            <button type="submit" className="btn-success" disabled={saving}>
              {saving ? 'Guardando…' : 'Crear bodega'}
            </button>
          </div>
        </form>
      )}

      {error && <ErrorBox message={error} />}

      {loading ? (
        <Loading />
      ) : warehouses.length === 0 ? (
        <Empty label="No hay bodegas" />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="table w-full">
            <thead className="bg-slate-50">
              <tr>
                <th>Nombre</th>
                <th>Código ERP</th>
                <th>Tipo</th>
                <th>Estado</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {warehouses.map((w) => (
                <tr key={w.id}>
                  <td className="font-medium">{w.name}</td>
                  <td className="font-mono text-xs">{w.erp_storage_code ?? '—'}</td>
                  <td>{w.type ?? '—'}</td>
                  <td>
                    {w.is_active === false ? (
                      <span className="badge bg-slate-200 text-slate-600">inactivo</span>
                    ) : (
                      <span className="badge bg-emerald-100 text-emerald-800">activo</span>
                    )}
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
