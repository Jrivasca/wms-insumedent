import { useEffect, useState } from 'react';
import {
  createLocation,
  listLocations,
  listWarehouses,
  updateLocation,
  type LocationInput,
} from '../api/warehouses';
import { errorMessage } from '../api/http';
import { Empty, ErrorBox, Loading, PageHeader } from '../components/Async';
import { can } from '../permissions';
import { useAuth } from '../store/auth';
import type { Location, Warehouse } from '../types';

const LOCATION_TYPES = ['storage', 'picking', 'staging', 'packing', 'dispatch', 'quarantine'];
const EMPTY_DETAIL = { name: '', type: 'storage', zone: '', aisle: '', rack: '', level: '', bin: '' };
type Detail = typeof EMPTY_DETAIL;

/** Trim text fields, dropping empties so we don't send blank strings. */
function cleanDetail(d: Detail): LocationInput {
  const out: LocationInput = { type: d.type };
  for (const k of ['name', 'zone', 'aisle', 'rack', 'level', 'bin'] as const) {
    const v = d[k].trim();
    if (v) out[k] = v;
  }
  return out;
}

export default function LocationsPage() {
  const { currentUser } = useAuth();
  const canEdit = can(currentUser?.role); // admin / supervisor

  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [locations, setLocations] = useState<Location[]>([]);
  const [filterWarehouse, setFilterWarehouse] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // create
  const [showForm, setShowForm] = useState(false);
  const [warehouseId, setWarehouseId] = useState('');
  const [code, setCode] = useState('');
  const [detail, setDetail] = useState<Detail>({ ...EMPTY_DETAIL });
  const [saving, setSaving] = useState(false);

  // edit
  const [editing, setEditing] = useState<Location | null>(null);
  const [editCode, setEditCode] = useState('');
  const [editDetail, setEditDetail] = useState<Detail>({ ...EMPTY_DETAIL });
  const [editActive, setEditActive] = useState(true);
  const [savingEdit, setSavingEdit] = useState(false);

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
      await createLocation({ warehouse_id: warehouseId, code: code.trim(), ...cleanDetail(detail) });
      setCode('');
      setDetail({ ...EMPTY_DETAIL });
      setShowForm(false);
      loadLocations(filterWarehouse);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  function openEdit(l: Location) {
    setEditing(l);
    setEditCode(l.code);
    setEditDetail({
      name: l.name ?? '',
      type: l.type ?? 'storage',
      zone: l.zone ?? '',
      aisle: l.aisle ?? '',
      rack: l.rack ?? '',
      level: l.level ?? '',
      bin: l.bin ?? '',
    });
    setEditActive(l.is_active !== false);
    setError(null);
  }

  async function handleSaveEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!editing) return;
    if (!editCode.trim()) {
      setError('El código no puede estar vacío.');
      return;
    }
    setSavingEdit(true);
    setError(null);
    try {
      await updateLocation(editing.id, {
        code: editCode.trim(),
        ...cleanDetail(editDetail),
        is_active: editActive,
      });
      setEditing(null);
      loadLocations(filterWarehouse);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSavingEdit(false);
    }
  }

  return (
    <div>
      <PageHeader
        title="Ubicaciones"
        actions={
          canEdit ? (
            <button onClick={() => setShowForm((v) => !v)} className="btn-primary">
              {showForm ? 'Cerrar' : 'Nueva ubicación'}
            </button>
          ) : undefined
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

      {showForm && canEdit && (
        <form onSubmit={handleCreate} className="card mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
          <div className="col-span-2 md:col-span-1">
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
            <input value={detail.name} onChange={(e) => setDetail({ ...detail, name: e.target.value })} className="input" />
          </div>
          <div>
            <label className="label">Tipo</label>
            <select value={detail.type} onChange={(e) => setDetail({ ...detail, type: e.target.value })} className="input">
              {LOCATION_TYPES.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>
          <DetailFields value={detail} onChange={setDetail} />
          <div className="col-span-2 md:col-span-4">
            <button type="submit" className="btn-success" disabled={saving}>
              {saving ? 'Guardando…' : 'Crear ubicación'}
            </button>
          </div>
        </form>
      )}

      {error && !editing && <ErrorBox message={error} />}

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
                <th>Estado</th>
                {canEdit && <th></th>}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {locations.map((l) => (
                <tr key={l.id} className={l.is_active === false ? 'opacity-60' : ''}>
                  <td className="font-mono text-xs">{l.code}</td>
                  <td>{l.name ?? '—'}</td>
                  <td>{warehouseName(l.warehouse_id)}</td>
                  <td>{l.type ?? '—'}</td>
                  <td className="text-xs text-slate-500">
                    {[l.zone, l.aisle, l.rack, l.level, l.bin].filter(Boolean).join(' / ') || '—'}
                  </td>
                  <td>
                    {l.is_active === false ? (
                      <span className="badge bg-slate-200 text-slate-600">inactiva</span>
                    ) : (
                      <span className="badge bg-emerald-100 text-emerald-800">activa</span>
                    )}
                  </td>
                  {canEdit && (
                    <td>
                      <button onClick={() => openEdit(l)} className="btn-secondary whitespace-nowrap">
                        Editar
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {editing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <form
            onSubmit={handleSaveEdit}
            className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-lg bg-white p-4"
          >
            <h3 className="text-lg font-bold">Editar ubicación</h3>
            <p className="mb-3 text-xs text-slate-500">
              Bodega: {warehouseName(editing.warehouse_id)} · la bodega no se puede cambiar.
            </p>
            {error && <ErrorBox message={error} />}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label">Código</label>
                <input value={editCode} onChange={(e) => setEditCode(e.target.value)} className="input" required />
              </div>
              <div>
                <label className="label">Nombre</label>
                <input
                  value={editDetail.name}
                  onChange={(e) => setEditDetail({ ...editDetail, name: e.target.value })}
                  className="input"
                />
              </div>
              <div>
                <label className="label">Tipo</label>
                <select
                  value={editDetail.type}
                  onChange={(e) => setEditDetail({ ...editDetail, type: e.target.value })}
                  className="input"
                >
                  {LOCATION_TYPES.map((t) => (
                    <option key={t} value={t}>{t}</option>
                  ))}
                </select>
              </div>
              <div className="flex items-end">
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={editActive} onChange={(e) => setEditActive(e.target.checked)} />
                  Activa
                </label>
              </div>
              <DetailFields value={editDetail} onChange={setEditDetail} />
            </div>
            <div className="mt-4 flex gap-2">
              <button type="submit" className="btn-success flex-1" disabled={savingEdit}>
                {savingEdit ? 'Guardando…' : 'Guardar cambios'}
              </button>
              <button type="button" onClick={() => setEditing(null)} className="btn-secondary flex-1">
                Cancelar
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}

/** The zona/pasillo/rack/nivel/bin detail inputs, shared by create and edit. */
function DetailFields({ value, onChange }: { value: Detail; onChange: (d: Detail) => void }) {
  const fields: { key: keyof Detail; label: string }[] = [
    { key: 'zone', label: 'Zona' },
    { key: 'aisle', label: 'Pasillo' },
    { key: 'rack', label: 'Rack' },
    { key: 'level', label: 'Nivel' },
    { key: 'bin', label: 'Bin' },
  ];
  return (
    <>
      {fields.map((f) => (
        <div key={f.key}>
          <label className="label">{f.label}</label>
          <input
            value={value[f.key]}
            onChange={(e) => onChange({ ...value, [f.key]: e.target.value })}
            className="input"
          />
        </div>
      ))}
    </>
  );
}
