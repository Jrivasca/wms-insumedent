import { useEffect, useState } from 'react';
import { Ban, Check, CheckCheck, Pencil, Plus, X } from 'lucide-react';
import { createUser, listUsers, updateUser } from '../api/users';
import { errorMessage } from '../api/http';
import { Empty, ErrorBox, LoadingRows, PageHeader } from '../components/Async';
import DataTable, { MobileCardList, type Column } from '../components/DataTable';
import { Field, SelectField } from '../components/Form';
import StatusBadge from '../components/StatusBadge';
import { ROLE_OPTIONS } from '../permissions';
import { useAuth } from '../store/auth';
import type { User } from '../types';

const ROLES = ROLE_OPTIONS;

const EMPTY = { name: '', email: '', password: '', role: 'picker' };

export default function UsersPage() {
  const { currentUser } = useAuth();
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [showCreate, setShowCreate] = useState(false);
  const [nu, setNu] = useState({ ...EMPTY });

  const [resetFor, setResetFor] = useState<User | null>(null);
  const [newPassword, setNewPassword] = useState('');

  // editar nombre / correo
  const [editFor, setEditFor] = useState<User | null>(null);
  const [editName, setEditName] = useState('');
  const [editEmail, setEditEmail] = useState('');

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setUsers(await listUsers());
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
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const created = await createUser({
        name: nu.name.trim(),
        email: nu.email.trim(),
        password: nu.password,
        role: nu.role,
      });
      setNotice(`Usuario creado: ${created.email}`);
      setNu({ ...EMPTY });
      setShowCreate(false);
      load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function changeRole(u: User, role: string) {
    setError(null);
    setNotice(null);
    try {
      await updateUser(u.id, { role });
      setNotice(`Rol de ${u.email} actualizado`);
      load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function toggleActive(u: User) {
    setError(null);
    setNotice(null);
    try {
      await updateUser(u.id, { is_active: u.is_active === false });
      setNotice(`${u.email} ${u.is_active === false ? 'activado' : 'desactivado'}`);
      load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function submitEdit() {
    if (!editFor || !editName.trim() || !editEmail.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await updateUser(editFor.id, { name: editName.trim(), email: editEmail.trim() });
      setNotice(`Datos actualizados: ${editEmail.trim()}`);
      setEditFor(null);
      load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function submitReset() {
    if (!resetFor || newPassword.length < 4) return;
    setBusy(true);
    setError(null);
    try {
      await updateUser(resetFor.id, { password: newPassword });
      setNotice(`Contraseña actualizada para ${resetFor.email}`);
      setResetFor(null);
      setNewPassword('');
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  function RowActions({ u, isSelf }: { u: User; isSelf: boolean }) {
    return (
      <div className="flex flex-wrap gap-2 lg:justify-end">
        <button
          onClick={() => {
            setEditFor(u);
            setEditName(u.name);
            setEditEmail(u.email);
          }}
          className="btn-secondary btn-sm whitespace-nowrap"
        >
          <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
          Editar
        </button>
        <button
          onClick={() => {
            setResetFor(u);
            setNewPassword('');
          }}
          className="btn-secondary btn-sm whitespace-nowrap"
        >
          Cambiar clave
        </button>
        <button
          onClick={() => toggleActive(u)}
          disabled={isSelf}
          title={isSelf ? 'No puedes desactivar tu propia cuenta' : undefined}
          className="btn-secondary btn-sm whitespace-nowrap disabled:opacity-40"
        >
          {u.is_active === false ? (
            <>
              <Check className="h-3.5 w-3.5" aria-hidden="true" />
              Activar
            </>
          ) : (
            <>
              <Ban className="h-3.5 w-3.5" aria-hidden="true" />
              Desactivar
            </>
          )}
        </button>
      </div>
    );
  }

  const columns: Column<User>[] = [
    {
      key: 'name',
      header: 'Nombre',
      render: (u) => (
        <span className="flex flex-wrap items-center gap-2">
          <span className="font-medium text-slate-900">{u.name}</span>
          {u.id === currentUser?.id && (
            <span className="badge bg-brand-soft text-brand-darker">tú</span>
          )}
        </span>
      ),
    },
    {
      key: 'email',
      header: 'Correo',
      render: (u) => <span className="text-sm text-slate-600">{u.email}</span>,
    },
    {
      key: 'role',
      header: 'Rol',
      render: (u) => {
        const isSelf = u.id === currentUser?.id;
        return (
          <select
            value={u.role}
            onChange={(e) => changeRole(u, e.target.value)}
            disabled={isSelf}
            title={isSelf ? 'No puedes cambiar tu propio rol' : undefined}
            className="input max-w-[12rem] disabled:opacity-60"
            aria-label={`Rol de ${u.name}`}
          >
            {ROLES.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </select>
        );
      },
    },
    {
      key: 'status',
      header: 'Estado',
      render: (u) => <StatusBadge status={u.is_active === false ? 'inactive' : 'active'} />,
    },
    {
      key: 'actions',
      header: '',
      align: 'right',
      render: (u) => <RowActions u={u} isSelf={u.id === currentUser?.id} />,
    },
  ];

  return (
    <div>
      <PageHeader
        title="Usuarios"
        subtitle="Equipo de la empresa: acceso y roles"
        actions={
          <button onClick={() => setShowCreate((v) => !v)} className="btn-primary">
            {showCreate ? (
              <>
                <X className="h-4 w-4" aria-hidden="true" />
                Cerrar
              </>
            ) : (
              <>
                <Plus className="h-4 w-4" aria-hidden="true" />
                Nuevo usuario
              </>
            )}
          </button>
        }
      />

      {notice && (
        <div className="mb-3 flex items-start gap-2 rounded-card border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
          <CheckCheck className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          {notice}
        </div>
      )}
      {error && <ErrorBox message={error} onRetry={load} />}

      {showCreate && (
        <form onSubmit={handleCreate} className="card mb-4 grid grid-cols-1 gap-3 md:grid-cols-2">
          <Field
            label="Nombre *"
            value={nu.name}
            onChange={(v) => setNu({ ...nu, name: v })}
            required
          />
          <Field
            label="Correo *"
            type="email"
            value={nu.email}
            onChange={(v) => setNu({ ...nu, email: v })}
            required
          />
          <Field
            label="Contraseña *"
            type="password"
            value={nu.password}
            onChange={(v) => setNu({ ...nu, password: v })}
            required
          />
          <SelectField
            label="Rol"
            value={nu.role}
            onChange={(v) => setNu({ ...nu, role: v })}
            options={ROLES}
            required
          />
          <div className="flex items-end md:col-span-2">
            <button type="submit" className="btn-success" disabled={busy}>
              {busy ? 'Creando…' : 'Crear usuario'}
            </button>
          </div>
        </form>
      )}

      {loading ? (
        <LoadingRows />
      ) : users.length === 0 ? (
        <Empty label="No hay usuarios" />
      ) : (
        <>
          <div className="hidden lg:block">
            <DataTable columns={columns} rows={users} keyOf={(u) => u.id} />
          </div>
          <div className="lg:hidden space-y-2">
            <MobileCardList
              rows={users}
              keyOf={(u) => u.id}
              render={(u) => {
                const isSelf = u.id === currentUser?.id;
                return (
                  <div>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="flex flex-wrap items-center gap-2">
                        <span className="font-medium text-slate-900">{u.name}</span>
                        {isSelf && (
                          <span className="badge bg-brand-soft text-brand-darker">tú</span>
                        )}
                      </span>
                      <StatusBadge status={u.is_active === false ? 'inactive' : 'active'} />
                    </div>
                    <p className="mt-0.5 truncate text-sm text-slate-600">{u.email}</p>
                    <div className="mt-2">
                      <label className="label" htmlFor={`role-${u.id}`}>
                        Rol
                      </label>
                      <select
                        id={`role-${u.id}`}
                        value={u.role}
                        onChange={(e) => changeRole(u, e.target.value)}
                        disabled={isSelf}
                        className="input disabled:opacity-60"
                      >
                        {ROLES.map((r) => (
                          <option key={r.value} value={r.value}>
                            {r.label}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div className="mt-2">
                      <RowActions u={u} isSelf={isSelf} />
                    </div>
                  </div>
                );
              }}
            />
          </div>
        </>
      )}

      <div className="card mt-4 space-y-1 text-xs text-slate-500">
        <p>
          <strong className="text-slate-700">Administrador / Supervisor:</strong> acceso completo y
          aprobaciones (ajustes, picking parcial, diferencias de packing).
        </p>
        <p>
          <strong className="text-slate-700">Ventas:</strong> crea y ve pedidos ·{' '}
          <strong className="text-slate-700">Bodega:</strong> hace picking y packing de sus tareas ·{' '}
          <strong className="text-slate-700">Despacho:</strong> confirma los envíos.
        </p>
      </div>

      {editFor && (
        <div
          className="fixed inset-0 z-50 flex items-end justify-center bg-graphite-950/50 p-4 sm:items-center"
          role="dialog"
          aria-modal="true"
          aria-labelledby="edit-user-title"
        >
          <div className="w-full max-w-sm rounded-card bg-white p-5 shadow-raised">
            <h3 id="edit-user-title" className="text-lg font-bold text-slate-900">
              Editar usuario
            </h3>
            <p className="mb-3 text-sm text-slate-500">{editFor.email}</p>
            <label className="label" htmlFor="edit-name">
              Nombre
            </label>
            <input
              id="edit-name"
              value={editName}
              onChange={(e) => setEditName(e.target.value)}
              className="input mb-3"
            />
            <label className="label" htmlFor="edit-email">
              Correo (con este inicia sesión)
            </label>
            <input
              id="edit-email"
              type="email"
              value={editEmail}
              onChange={(e) => setEditEmail(e.target.value)}
              className="input mb-3"
            />
            {editFor.id === currentUser?.id && (
              <p className="mb-3 rounded-card border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                Estás editando tu propia cuenta: si cambias el correo, la próxima vez deberás
                iniciar sesión con el nuevo.
              </p>
            )}
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button onClick={() => setEditFor(null)} className="btn-secondary">
                Cancelar
              </button>
              <button
                onClick={submitEdit}
                className="btn-primary"
                disabled={!editName.trim() || !editEmail.trim() || busy}
              >
                {busy ? 'Guardando…' : 'Guardar'}
              </button>
            </div>
          </div>
        </div>
      )}

      {resetFor && (
        <div
          className="fixed inset-0 z-50 flex items-end justify-center bg-graphite-950/50 p-4 sm:items-center"
          role="dialog"
          aria-modal="true"
          aria-labelledby="reset-pass-title"
        >
          <div className="w-full max-w-sm rounded-card bg-white p-5 shadow-raised">
            <h3 id="reset-pass-title" className="text-lg font-bold text-slate-900">
              Cambiar contraseña
            </h3>
            <p className="mb-3 text-sm text-slate-500">{resetFor.email}</p>
            <label className="label" htmlFor="new-pass">
              Nueva contraseña (mínimo 4 caracteres)
            </label>
            <input
              id="new-pass"
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              className="input mb-1"
              autoComplete="new-password"
            />
            <p className="hint mb-3">
              La persona la usará en su próximo inicio de sesión. Conviene que la cambie ella
              después.
            </p>
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button onClick={() => setResetFor(null)} className="btn-secondary">
                Cancelar
              </button>
              <button
                onClick={submitReset}
                className="btn-primary"
                disabled={newPassword.length < 4 || busy}
              >
                {busy ? 'Guardando…' : 'Guardar'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
