import { useEffect, useState } from 'react';
import { Pencil, Plus, X } from 'lucide-react';
import {
  createLocation,
  listLocations,
  listWarehouses,
  updateLocation,
  type LocationInput,
} from '../api/warehouses';
import { errorMessage } from '../api/http';
import { Empty, ErrorBox, LoadingRows, PageHeader } from '../components/Async';
import DataTable, { MobileCardList, type Column } from '../components/DataTable';
import StatusBadge from '../components/StatusBadge';
import { can } from '../permissions';
import { useAuth } from '../store/auth';
import type { Location, Warehouse } from '../types';

const LOCATION_TYPES = [
  'storage',
  'picking',
  'receiving',
  'staging',
  'packing',
  'dispatch',
  'quarantine',
];

/** Los valores viajan igual al backend; solo cambia cómo se leen. */
const LOCATION_TYPE_LABEL: Record<string, string> = {
  storage: 'Almacenamiento',
  picking: 'Picking',
  receiving: 'Recepción (sin ubicar)',
  staging: 'Preparación',
  packing: 'Packing',
  dispatch: 'Despacho',
  quarantine: 'Cuarentena',
};

function typeLabel(type?: string | null): string {
  if (!type) return '—';
  return LOCATION_TYPE_LABEL[type] ?? type;
}

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

  const detailText = (l: Location) =>
    [l.zone, l.aisle, l.rack, l.level, l.bin].filter(Boolean).join(' / ') || '—';

  const columns: Column<Location>[] = [
    { key: 'code', header: 'Código', render: (l) => <span className="code-strong">{l.code}</span> },
    {
      key: 'name',
      header: 'Nombre',
      render: (l) => <span className="text-slate-700">{l.name ?? '—'}</span>,
    },
    { key: 'warehouse', header: 'Bodega', render: (l) => warehouseName(l.warehouse_id) },
    { key: 'type', header: 'Tipo', render: (l) => typeLabel(l.type) },
    {
      key: 'detail',
      header: 'Zona / Pasillo / Rack / Nivel / Bin',
      secondary: true,
      render: (l) => <span className="text-xs text-slate-500">{detailText(l)}</span>,
    },
    {
      key: 'status',
      header: 'Estado',
      render: (l) => <StatusBadge status={l.is_active === false ? 'inactive' : 'active'} />,
    },
    ...(canEdit
      ? [
          {
            key: 'actions',
            header: '',
            align: 'right' as const,
            render: (l: Location) => (
              <button onClick={() => openEdit(l)} className="btn-secondary btn-sm whitespace-nowrap">
                <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
                Editar
              </button>
            ),
          },
        ]
      : []),
  ];

  return (
    <div>
      <PageHeader
        title="Ubicaciones"
        subtitle="Las posiciones donde se guarda el stock dentro de cada bodega"
        actions={
          canEdit ? (
            <button onClick={() => setShowForm((v) => !v)} className="btn-primary">
              {showForm ? (
                <>
                  <X className="h-4 w-4" aria-hidden="true" />
                  Cerrar
                </>
              ) : (
                <>
                  <Plus className="h-4 w-4" aria-hidden="true" />
                  Nueva ubicación
                </>
              )}
            </button>
          ) : undefined
        }
      />

      <div className="mb-4 max-w-xs">
        <label className="label" htmlFor="loc-filter">
          Filtrar por bodega
        </label>
        <select
          id="loc-filter"
          value={filterWarehouse}
          onChange={(e) => {
            setFilterWarehouse(e.target.value);
            loadLocations(e.target.value);
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

      {showForm && canEdit && (
        <form onSubmit={handleCreate} className="card mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
          <div className="col-span-2 md:col-span-1">
            <label className="label" htmlFor="new-wh">
              Bodega
            </label>
            <select
              id="new-wh"
              value={warehouseId}
              onChange={(e) => setWarehouseId(e.target.value)}
              className="input"
              required
            >
              <option value="">Seleccione…</option>
              {warehouses.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="label" htmlFor="new-code">
              Código
            </label>
            <input
              id="new-code"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              className="input"
              required
            />
          </div>
          <div>
            <label className="label" htmlFor="new-name">
              Nombre
            </label>
            <input
              id="new-name"
              value={detail.name}
              onChange={(e) => setDetail({ ...detail, name: e.target.value })}
              className="input"
            />
          </div>
          <div>
            <label className="label" htmlFor="new-type">
              Tipo
            </label>
            <select
              id="new-type"
              value={detail.type}
              onChange={(e) => setDetail({ ...detail, type: e.target.value })}
              className="input"
            >
              {LOCATION_TYPES.map((t) => (
                <option key={t} value={t}>
                  {typeLabel(t)}
                </option>
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
        <LoadingRows />
      ) : locations.length === 0 ? (
        <Empty
          label="No hay ubicaciones"
          hint="Sin ubicaciones no se puede recibir ni mover stock: crea al menos una por bodega."
        />
      ) : (
        <>
          <div className="hidden lg:block">
            <DataTable
              columns={columns}
              rows={locations}
              keyOf={(l) => l.id}
              rowClassName={(l) => (l.is_active === false ? 'opacity-60' : undefined)}
            />
          </div>
          <div className="lg:hidden">
            <MobileCardList
              rows={locations}
              keyOf={(l) => l.id}
              render={(l) => (
                <div className={l.is_active === false ? 'opacity-60' : undefined}>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="code-strong">{l.code}</span>
                    <StatusBadge status={l.is_active === false ? 'inactive' : 'active'} />
                  </div>
                  <p className="mt-0.5 text-sm text-slate-700">{l.name ?? '—'}</p>
                  <p className="mt-1 text-xs text-slate-500">
                    {warehouseName(l.warehouse_id)} · {typeLabel(l.type)}
                  </p>
                  {detailText(l) !== '—' && (
                    <p className="mt-0.5 text-xs text-slate-500">{detailText(l)}</p>
                  )}
                  {canEdit && (
                    <button
                      onClick={() => openEdit(l)}
                      className="btn-secondary btn-sm mt-2 whitespace-nowrap"
                    >
                      <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
                      Editar
                    </button>
                  )}
                </div>
              )}
            />
          </div>
        </>
      )}

      {editing && (
        <div
          className="fixed inset-0 z-50 flex items-end justify-center bg-graphite-950/50 p-4 sm:items-center"
          role="dialog"
          aria-modal="true"
          aria-labelledby="edit-loc-title"
        >
          <form
            onSubmit={handleSaveEdit}
            className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-card bg-white p-5 shadow-raised"
          >
            <h3 id="edit-loc-title" className="text-lg font-bold text-slate-900">
              Editar ubicación
            </h3>
            <p className="mb-3 text-xs text-slate-500">
              Bodega: {warehouseName(editing.warehouse_id)} · la bodega no se puede cambiar.
            </p>
            {error && <ErrorBox message={error} />}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label" htmlFor="edit-code">
                  Código
                </label>
                <input
                  id="edit-code"
                  value={editCode}
                  onChange={(e) => setEditCode(e.target.value)}
                  className="input"
                  required
                />
              </div>
              <div>
                <label className="label" htmlFor="edit-name-loc">
                  Nombre
                </label>
                <input
                  id="edit-name-loc"
                  value={editDetail.name}
                  onChange={(e) => setEditDetail({ ...editDetail, name: e.target.value })}
                  className="input"
                />
              </div>
              <div>
                <label className="label" htmlFor="edit-type">
                  Tipo
                </label>
                <select
                  id="edit-type"
                  value={editDetail.type}
                  onChange={(e) => setEditDetail({ ...editDetail, type: e.target.value })}
                  className="input"
                >
                  {LOCATION_TYPES.map((t) => (
                    <option key={t} value={t}>
                      {typeLabel(t)}
                    </option>
                  ))}
                </select>
              </div>
              <div className="flex items-end">
                <label className="flex min-h-touch items-center gap-2 text-sm text-slate-700">
                  <input
                    type="checkbox"
                    className="h-4 w-4 rounded border-slate-300 text-brand focus:ring-brand"
                    checked={editActive}
                    onChange={(e) => setEditActive(e.target.checked)}
                  />
                  Activa
                </label>
              </div>
              <DetailFields value={editDetail} onChange={setEditDetail} />
            </div>
            <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button type="button" onClick={() => setEditing(null)} className="btn-secondary">
                Cancelar
              </button>
              <button type="submit" className="btn-primary" disabled={savingEdit}>
                {savingEdit ? 'Guardando…' : 'Guardar cambios'}
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
          <label className="label" htmlFor={`detail-${f.key}`}>
            {f.label}
          </label>
          <input
            id={`detail-${f.key}`}
            value={value[f.key]}
            onChange={(e) => onChange({ ...value, [f.key]: e.target.value })}
            className="input"
          />
        </div>
      ))}
    </>
  );
}
