import { useEffect, useState } from 'react';
import { createUser, listUsers, updateUser } from '../api/users';
import { errorMessage } from '../api/http';
import { Empty, ErrorBox, Loading, PageHeader } from '../components/Async';
import { Field, SelectField } from '../components/Form';
import type { User } from '../types';

const ROLES = [
  { value: 'admin', label: 'Administrador' },
  { value: 'supervisor', label: 'Supervisor' },
  { value: 'picker', label: 'Picking' },
  { value: 'packer', label: 'Packing' },
  { value: 'receiver', label: 'Recepción' },
  { value: 'auditor', label: 'Auditor' },
];

const ROLE_LABEL: Record<string, string> = Object.fromEntries(
  ROLES.map((r) => [r.value, r.label])
);

const EMPTY = { name: '', email: '', password: '', role: 'picker' };

export default function UsersPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [showCreate, setShowCreate] = useState(false);
  const [nu, setNu] = useState({ ...EMPTY });

  const [resetFor, setResetFor] = useState<User | null>(null);
  const [newPassword, setNewPassword] = useState('');

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

  return (
    <div>
      <PageHeader
        title="Usuarios"
        subtitle="Equipo de la empresa: acceso y roles"
        actions={
          <button onClick={() => setShowCreate((v) => !v)} className="btn-primary">
            {showCreate ? 'Cerrar' : '+ Nuevo usuario'}
          </button>
        }
      />

      {notice && (
        <div className="mb-3 rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-700">{notice}</div>
      )}
      {error && <ErrorBox message={error} />}

      {showCreate && (
        <form onSubmit={handleCreate} className="card mb-4 grid grid-cols-1 gap-3 md:grid-cols-2">
          <Field label="Nombre *" value={nu.name} onChange={(v) => setNu({ ...nu, name: v })} required />
          <Field label="Email *" type="email" value={nu.email} onChange={(v) => setNu({ ...nu, email: v })} required />
          <Field
            label="Contraseña *"
            type="password"
            value={nu.password}
            onChange={(v) => setNu({ ...nu, password: v })}
            required
          />
          <SelectField label="Rol" value={nu.role} onChange={(v) => setNu({ ...nu, role: v })} options={ROLES} required />
          <div className="flex items-end md:col-span-2">
            <button type="submit" className="btn-success" disabled={busy}>
              {busy ? 'Creando…' : 'Crear usuario'}
            </button>
          </div>
        </form>
      )}

      {loading ? (
        <Loading />
      ) : users.length === 0 ? (
        <Empty label="No hay usuarios" />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="table w-full">
            <thead className="bg-slate-50">
              <tr>
                <th>Nombre</th>
                <th>Email</th>
                <th>Rol</th>
                <th>Estado</th>
                <th></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {users.map((u) => (
                <tr key={u.id}>
                  <td className="font-medium">{u.name}</td>
                  <td className="text-sm text-slate-600">{u.email}</td>
                  <td>
                    <select
                      value={u.role}
                      onChange={(e) => changeRole(u, e.target.value)}
                      className="input max-w-[10rem]"
                    >
                      {ROLES.map((r) => (
                        <option key={r.value} value={r.value}>
                          {r.label}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    {u.is_active === false ? (
                      <span className="badge bg-slate-200 text-slate-600">inactivo</span>
                    ) : (
                      <span className="badge bg-emerald-100 text-emerald-800">activo</span>
                    )}
                  </td>
                  <td>
                    <div className="flex flex-wrap gap-2">
                      <button
                        onClick={() => {
                          setResetFor(u);
                          setNewPassword('');
                        }}
                        className="btn-secondary whitespace-nowrap"
                      >
                        Cambiar clave
                      </button>
                      <button onClick={() => toggleActive(u)} className="btn-secondary whitespace-nowrap">
                        {u.is_active === false ? 'Activar' : 'Desactivar'}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="mt-3 text-xs text-slate-500">
        {ROLE_LABEL.admin} y {ROLE_LABEL.supervisor} pueden aprobar ajustes, picking parcial y
        diferencias de packing. Los demás roles operan en piso.
      </p>

      {resetFor && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-sm rounded-lg bg-white p-4">
            <h3 className="text-lg font-bold">Cambiar contraseña</h3>
            <p className="mb-3 text-sm text-slate-500">{resetFor.email}</p>
            <label className="label">Nueva contraseña (mín. 4)</label>
            <input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              className="input mb-3"
            />
            <div className="flex gap-2">
              <button
                onClick={submitReset}
                className="btn-success flex-1"
                disabled={newPassword.length < 4 || busy}
              >
                Guardar
              </button>
              <button onClick={() => setResetFor(null)} className="btn-secondary flex-1">
                Cancelar
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
