import { useEffect, useState } from 'react';
import { Plus, X } from 'lucide-react';
import { createWarehouse, listWarehouses } from '../api/warehouses';
import { errorMessage } from '../api/http';
import { Empty, ErrorBox, LoadingRows, PageHeader } from '../components/Async';
import DataTable, { MobileCardList, type Column } from '../components/DataTable';
import StatusBadge from '../components/StatusBadge';
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

  const columns: Column<Warehouse>[] = [
    {
      key: 'name',
      header: 'Nombre',
      render: (w) => <span className="font-medium text-slate-900">{w.name}</span>,
    },
    {
      key: 'erp',
      header: 'Código en Defontana',
      render: (w) =>
        w.erp_storage_code ? (
          <span className="code-strong">{w.erp_storage_code}</span>
        ) : (
          <span className="text-xs text-amber-800">Sin código</span>
        ),
    },
    { key: 'type', header: 'Tipo', secondary: true, render: (w) => w.type ?? '—' },
    {
      key: 'status',
      header: 'Estado',
      render: (w) => <StatusBadge status={w.is_active === false ? 'inactive' : 'active'} />,
    },
  ];

  return (
    <div>
      <PageHeader
        title="Bodegas"
        subtitle="Las bodegas del WMS y su equivalencia en Defontana"
        actions={
          <button onClick={() => setShowForm((v) => !v)} className="btn-primary">
            {showForm ? (
              <>
                <X className="h-4 w-4" aria-hidden="true" />
                Cerrar
              </>
            ) : (
              <>
                <Plus className="h-4 w-4" aria-hidden="true" />
                Nueva bodega
              </>
            )}
          </button>
        }
      />

      {showForm && (
        <form onSubmit={handleCreate} className="card mb-4 grid grid-cols-1 gap-3 md:grid-cols-3">
          <div>
            <label className="label" htmlFor="wh-name">
              Nombre
            </label>
            <input
              id="wh-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="input"
              required
            />
          </div>
          <div>
            <label className="label" htmlFor="wh-erp">
              Código en Defontana
            </label>
            <input
              id="wh-erp"
              value={erpCode}
              onChange={(e) => setErpCode(e.target.value)}
              className="input"
              placeholder="Ej: BODEGACENTRAL"
            />
            <p className="hint">
              Debe ser igual al código de bodega en Defontana. Si no coincide, la comparación de
              stock no puede cuadrar.
            </p>
          </div>
          <div>
            <label className="label" htmlFor="wh-type">
              Tipo
            </label>
            <input
              id="wh-type"
              value={type}
              onChange={(e) => setType(e.target.value)}
              className="input"
              placeholder="main / quarantine…"
            />
          </div>
          <div className="md:col-span-3">
            <button type="submit" className="btn-success" disabled={saving}>
              {saving ? 'Guardando…' : 'Crear bodega'}
            </button>
          </div>
        </form>
      )}

      {error && <ErrorBox message={error} onRetry={load} />}

      {loading ? (
        <LoadingRows rows={3} />
      ) : warehouses.length === 0 ? (
        <Empty
          label="No hay bodegas"
          hint="Crea la bodega que existe en Defontana para que el stock pueda compararse."
        />
      ) : (
        <>
          <div className="hidden lg:block">
            <DataTable columns={columns} rows={warehouses} keyOf={(w) => w.id} />
          </div>
          <div className="lg:hidden">
            <MobileCardList
              rows={warehouses}
              keyOf={(w) => w.id}
              render={(w) => (
                <div>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-medium text-slate-900">{w.name}</span>
                    <StatusBadge status={w.is_active === false ? 'inactive' : 'active'} />
                  </div>
                  <p className="mt-1 text-xs text-slate-500">
                    Defontana:{' '}
                    {w.erp_storage_code ? (
                      <span className="code">{w.erp_storage_code}</span>
                    ) : (
                      <span className="text-amber-800">sin código</span>
                    )}
                    {w.type && <> · {w.type}</>}
                  </p>
                </div>
              )}
            />
          </div>
        </>
      )}
    </div>
  );
}
