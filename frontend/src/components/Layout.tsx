import { useState } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import type { ReactNode } from 'react';
import { useAuth } from '../store/auth';
import { FLOOR_ROLES, ROLE_LABEL, can } from '../permissions';

interface NavItem {
  to?: string;
  label: string;
  children?: NavItem[];
  /** Roles extra que ven esta sección (admin/supervisor siempre la ven). */
  roles?: string[];
}

const NAV: NavItem[] = [
  { to: '/', label: 'Dashboard' },
  { to: '/products', label: 'Productos' },
  { to: '/labels', label: 'Etiquetas' },
  { to: '/warehouses', label: 'Bodegas' },
  { to: '/locations', label: 'Ubicaciones' },
  {
    label: 'Inventario',
    children: [
      { to: '/inventory', label: 'Saldos' },
      { to: '/inventory/recepcion', label: 'Recepción' },
      { to: '/inventory/transferencia', label: 'Transferencia' },
      { to: '/inventory/ajuste', label: 'Ajuste' },
    ],
  },
  { to: '/orders', label: 'Pedidos', roles: ['sales'] },
  { to: '/picking', label: 'Picking' },
  { to: '/packing', label: 'Packing' },
  { to: '/dispatch', label: 'Despachos', roles: ['dispatcher'] },
  { to: '/usuarios', label: 'Usuarios' },
  { to: '/settings/defontana', label: 'Config. Defontana' },
  { to: '/sync-jobs', label: 'Cola de Sincronización' },
];

const MY_TASKS_NAV: NavItem[] = [
  { to: '/my/picking', label: 'Mis tareas de picking', roles: FLOOR_ROLES },
  { to: '/my/packing', label: 'Mis tareas de packing', roles: FLOOR_ROLES },
];

export default function Layout({ children }: { children: ReactNode }) {
  const { currentUser, logout } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);

  const role = currentUser?.role;
  const items = [...NAV, ...MY_TASKS_NAV].filter((it) => can(role, it.roles));

  async function handleLogout() {
    await logout();
    navigate('/login', { replace: true });
  }

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    `block rounded-md px-3 py-2 text-sm font-medium ${
      isActive ? 'bg-brand text-white' : 'text-slate-300 hover:bg-slate-700 hover:text-white'
    }`;

  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      {/* Sidebar (desktop) / top bar (mobile) */}
      <header className="flex items-center justify-between bg-slate-900 px-4 py-3 text-white md:hidden print:hidden">
        <button onClick={() => setOpen((v) => !v)} className="rounded p-2 hover:bg-slate-700" aria-label="Menú">
          <span className="block h-0.5 w-6 bg-white" />
          <span className="mt-1.5 block h-0.5 w-6 bg-white" />
          <span className="mt-1.5 block h-0.5 w-6 bg-white" />
        </button>
        <span className="font-bold">WMS Insumedent</span>
        <button onClick={handleLogout} className="text-sm underline">
          Salir
        </button>
      </header>

      <aside
        className={`${
          open ? 'block' : 'hidden'
        } w-full shrink-0 bg-slate-900 p-4 text-white md:block md:w-64 print:hidden`}
      >
        <div className="mb-6 hidden md:block">
          <h1 className="text-lg font-bold">WMS Insumedent</h1>
          <p className="text-xs text-slate-400">{ROLE_LABEL[role ?? ''] ?? role ?? ''}</p>
        </div>

        <nav className="space-y-1">
          {items.map((it) =>
            it.children ? (
              <div key={it.label} className="pt-1">
                <div className="px-3 pb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  {it.label}
                </div>
                <div className="space-y-1">
                  {it.children.map((c) => (
                    <NavLink
                      key={c.to}
                      to={c.to!}
                      end
                      className={({ isActive }) =>
                        `block rounded-md px-3 py-2 pl-6 text-sm font-medium ${
                          isActive ? 'bg-brand text-white' : 'text-slate-300 hover:bg-slate-700 hover:text-white'
                        }`
                      }
                      onClick={() => setOpen(false)}
                    >
                      {c.label}
                    </NavLink>
                  ))}
                </div>
              </div>
            ) : (
              <NavLink key={it.to} to={it.to!} end={it.to === '/'} className={linkClass} onClick={() => setOpen(false)}>
                {it.label}
              </NavLink>
            )
          )}
        </nav>

        <div className="mt-6 border-t border-slate-700 pt-4">
          <div className="mb-2 text-sm">
            <div className="font-semibold">{currentUser?.name ?? 'Usuario'}</div>
            <div className="text-xs text-slate-400">
              {currentUser?.email} · {currentUser?.role}
            </div>
          </div>
          <button onClick={handleLogout} className="btn-secondary w-full">
            Cerrar sesión
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-x-hidden bg-slate-100 p-4 md:p-6">{children}</main>
    </div>
  );
}
