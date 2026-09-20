import { useEffect, useState } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import type { ComponentType, ReactNode } from 'react';
import {
  ArrowLeftRight,
  Boxes,
  ChevronDown,
  ClipboardCheck,
  ClipboardList,
  GitCompare,
  LayoutDashboard,
  ListChecks,
  LogOut,
  MapPin,
  Menu,
  MoveRight,
  Package,
  PackageCheck,
  PackagePlus,
  PackageSearch,
  PlugZap,
  RefreshCw,
  SlidersHorizontal,
  Tags,
  Truck,
  Users,
  Warehouse,
  X,
} from 'lucide-react';
import { useAuth } from '../store/auth';
import { FLOOR_ROLES, ROLE_LABEL, can } from '../permissions';
import NotificationBell from './NotificationBell';

type IconType = ComponentType<{ className?: string }>;

interface NavItem {
  to: string;
  label: string;
  icon: IconType;
  /** Roles extra que ven el ítem (admin/supervisor siempre lo ven). */
  roles?: string[];
  /** Activo solo en la ruta exacta: para rutas que son prefijo de otras. */
  exact?: boolean;
}

interface NavGroup {
  id: string;
  label: string;
  items: NavItem[];
}

/**
 * La navegación se agrupa por para qué entra cada quien: "Mis tareas" es el trabajo
 * asignado, "Control" es mirar el estado, "Operaciones" es mover mercadería y
 * "Administración" es configurar. Los ítems se filtran por rol y un grupo sin ítems
 * visibles desaparece.
 */
const GROUPS: NavGroup[] = [
  {
    id: 'tareas',
    label: 'Mis tareas',
    items: [
      { to: '/my/picking', label: 'Picking asignado', icon: ListChecks, roles: FLOOR_ROLES },
      { to: '/my/packing', label: 'Packing asignado', icon: ClipboardCheck, roles: FLOOR_ROLES },
    ],
  },
  {
    id: 'control',
    label: 'Control',
    items: [
      { to: '/', label: 'Resumen', icon: LayoutDashboard, exact: true },
      { to: '/orders', label: 'Pedidos', icon: ClipboardList, roles: ['sales'] },
    ],
  },
  {
    id: 'operaciones',
    label: 'Operaciones',
    items: [
      { to: '/picking', label: 'Picking', icon: PackageSearch },
      { to: '/packing', label: 'Packing', icon: PackageCheck },
      { to: '/dispatch', label: 'Despachos', icon: Truck, roles: ['dispatcher'] },
      { to: '/inventory', label: 'Inventario', icon: Boxes, exact: true },
      { to: '/inventory/recepcion', label: 'Recepción', icon: PackagePlus },
      { to: '/inventory/ubicar', label: 'Ubicar stock', icon: MoveRight },
      { to: '/inventory/transferencia', label: 'Transferencia', icon: ArrowLeftRight },
      { to: '/inventory/ajuste', label: 'Ajuste', icon: SlidersHorizontal },
      { to: '/inventory/erp-stock', label: 'Stock ERP vs WMS', icon: GitCompare },
    ],
  },
  {
    id: 'admin',
    label: 'Administración',
    items: [
      { to: '/products', label: 'Productos', icon: Package },
      { to: '/labels', label: 'Etiquetas', icon: Tags },
      { to: '/warehouses', label: 'Bodegas', icon: Warehouse },
      { to: '/locations', label: 'Ubicaciones', icon: MapPin },
      { to: '/usuarios', label: 'Usuarios', icon: Users },
      { to: '/settings/defontana', label: 'Defontana', icon: PlugZap },
      { to: '/sync-jobs', label: 'Cola de sincronización', icon: RefreshCw },
    ],
  },
];

/** Barra inferior en móvil: los cuatro destinos que se usan estando en piso. */
const BOTTOM: NavItem[] = [
  { to: '/', label: 'Resumen', icon: LayoutDashboard, exact: true },
  { to: '/orders', label: 'Pedidos', icon: ClipboardList, roles: ['sales'] },
  { to: '/my/picking', label: 'Mis tareas', icon: ListChecks, roles: FLOOR_ROLES },
  { to: '/inventory', label: 'Inventario', icon: Boxes, exact: true },
];

const COLLAPSED_KEY = 'wms.nav.collapsed';

function readCollapsed(): string[] {
  try {
    const raw = localStorage.getItem(COLLAPSED_KEY);
    return raw ? (JSON.parse(raw) as string[]) : [];
  } catch {
    return [];
  }
}

/** Nombre de la sección actual: da contexto en el header y en el título móvil. */
function sectionTitle(pathname: string): string {
  const all = GROUPS.flatMap((g) => g.items);
  const exact = all.find((i) => i.to === pathname);
  if (exact) return exact.label;
  const deepest = all
    .filter((i) => i.to !== '/' && pathname.startsWith(i.to))
    .sort((a, b) => b.to.length - a.to.length)[0];
  return deepest?.label ?? 'Selarix WMS';
}

function BrandBlock() {
  return (
    <div className="flex items-center gap-2.5 px-4 py-4">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-brand text-sm font-bold text-white">
        S
      </span>
      <span className="min-w-0">
        <span className="block truncate text-sm font-bold text-white">Selarix WMS</span>
        <span className="block truncate text-xs text-graphite-400">Insumedent</span>
      </span>
    </div>
  );
}

function NavLists({
  groups,
  collapsed,
  onToggleGroup,
  onNavigate,
}: {
  groups: NavGroup[];
  collapsed: string[];
  onToggleGroup: (id: string) => void;
  onNavigate?: () => void;
}) {
  return (
    <nav className="flex-1 overflow-y-auto px-2 pb-4">
      {groups.map((group) => {
        const isCollapsed = collapsed.includes(group.id);
        return (
          <div key={group.id} className="mb-1">
            <button
              type="button"
              onClick={() => onToggleGroup(group.id)}
              aria-expanded={!isCollapsed}
              className="flex w-full items-center justify-between rounded px-3 py-2 text-xs font-semibold uppercase tracking-wide text-graphite-400 transition hover:text-white"
            >
              <span>{group.label}</span>
              <ChevronDown
                className={`h-3.5 w-3.5 transition-transform ${isCollapsed ? '-rotate-90' : ''}`}
                aria-hidden="true"
              />
            </button>
            {!isCollapsed && (
              <div className="space-y-0.5 pb-1">
                {group.items.map(({ to, label, icon: ItemIcon, exact }) => (
                  <NavLink
                    key={to}
                    to={to}
                    end={exact}
                    onClick={onNavigate}
                    className={({ isActive }) =>
                      `flex min-h-touch items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium transition ${
                        isActive
                          ? 'bg-brand text-white'
                          : 'text-graphite-200 hover:bg-graphite-800 hover:text-white'
                      }`
                    }
                  >
                    <ItemIcon className="h-4 w-4 shrink-0" aria-hidden="true" />
                    <span className="truncate">{label}</span>
                  </NavLink>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </nav>
  );
}

function UserBlock({ onLogout }: { onLogout: () => void }) {
  const { currentUser } = useAuth();
  const role = currentUser?.role;
  return (
    <div className="border-t border-graphite-700 px-4 py-3">
      <div className="mb-2 min-w-0">
        <p className="truncate text-sm font-semibold text-white">
          {currentUser?.name ?? 'Usuario'}
        </p>
        <p className="truncate text-xs text-graphite-400">
          {ROLE_LABEL[role ?? ''] ?? role ?? ''}
        </p>
        <p className="truncate text-xs text-graphite-400">{currentUser?.email}</p>
      </div>
      <button
        type="button"
        onClick={onLogout}
        className="flex min-h-touch w-full items-center justify-center gap-2 rounded-md border border-graphite-700 px-3 py-2 text-sm font-medium text-graphite-200 transition hover:bg-graphite-800 hover:text-white"
      >
        <LogOut className="h-4 w-4" aria-hidden="true" />
        Cerrar sesión
      </button>
    </div>
  );
}

export default function Layout({ children }: { children: ReactNode }) {
  const { currentUser, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [drawer, setDrawer] = useState(false);
  const [collapsed, setCollapsed] = useState<string[]>(() => readCollapsed());

  const role = currentUser?.role;
  const groups = GROUPS.map((g) => ({
    ...g,
    items: g.items.filter((i) => can(role, i.roles)),
  })).filter((g) => g.items.length > 0);
  const bottom = BOTTOM.filter((i) => can(role, i.roles));
  const title = sectionTitle(location.pathname);

  // Al cambiar de pantalla el cajón se cierra solo.
  useEffect(() => {
    setDrawer(false);
  }, [location.pathname]);

  useEffect(() => {
    if (!drawer) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setDrawer(false);
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [drawer]);

  function toggleGroup(id: string) {
    setCollapsed((prev) => {
      const next = prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id];
      try {
        localStorage.setItem(COLLAPSED_KEY, JSON.stringify(next));
      } catch {
        /* sin persistencia: el menú sigue funcionando */
      }
      return next;
    });
  }

  async function handleLogout() {
    await logout();
    navigate('/login', { replace: true });
  }

  return (
    <div className="min-h-screen">
      {/* Navegación fija en escritorio */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 flex-col bg-graphite-900 md:flex print:hidden">
        <BrandBlock />
        <NavLists groups={groups} collapsed={collapsed} onToggleGroup={toggleGroup} />
        <UserBlock onLogout={handleLogout} />
      </aside>

      {/* Cajón en móvil */}
      {drawer && (
        <div className="fixed inset-0 z-40 md:hidden print:hidden">
          <div
            className="absolute inset-0 bg-graphite-950/60"
            onClick={() => setDrawer(false)}
            aria-hidden="true"
          />
          <div
            className="absolute inset-y-0 left-0 flex w-72 max-w-[85%] flex-col bg-graphite-900 shadow-raised"
            role="dialog"
            aria-modal="true"
            aria-label="Menú de navegación"
          >
            <div className="flex items-center justify-between">
              <BrandBlock />
              <button
                type="button"
                onClick={() => setDrawer(false)}
                className="mr-2 flex h-touch w-touch items-center justify-center rounded-md text-graphite-200 hover:bg-graphite-800 hover:text-white"
                aria-label="Cerrar menú"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <NavLists
              groups={groups}
              collapsed={collapsed}
              onToggleGroup={toggleGroup}
              onNavigate={() => setDrawer(false)}
            />
            <UserBlock onLogout={handleLogout} />
          </div>
        </div>
      )}

      <div className="flex min-h-screen flex-col md:pl-64">
        <header className="sticky top-0 z-20 flex items-center gap-2 border-b border-slate-200 bg-white/95 px-3 py-2 backdrop-blur md:px-6 md:py-3 print:hidden">
          <button
            type="button"
            onClick={() => setDrawer(true)}
            className="flex h-touch w-touch shrink-0 items-center justify-center rounded-md text-slate-600 hover:bg-slate-100 md:hidden"
            aria-label="Abrir menú"
          >
            <Menu className="h-6 w-6" />
          </button>
          {/* Contexto de navegación, no el título del documento: el <h1> lo pone cada
              pantalla (PageHeader o el encabezado propio de las tareas). */}
          <p className="min-w-0 flex-1 truncate text-base font-semibold text-slate-900 md:text-lg">
            {title}
          </p>
          <div className="flex shrink-0 items-center gap-1 text-slate-600">
            <NotificationBell />
          </div>
        </header>

        <main className="flex-1 px-4 pb-24 pt-4 md:px-6 md:pb-8 md:pt-6">{children}</main>

        {/* Barra inferior: destinos de piso, solo en móvil */}
        {bottom.length > 1 && (
          <nav className="safe-bottom fixed bottom-0 left-0 right-0 z-20 flex border-t border-slate-200 bg-white shadow-nav md:hidden print:hidden">
            {bottom.map(({ to, label, icon: ItemIcon, exact }) => (
              <NavLink
                key={to}
                to={to}
                end={exact}
                className={({ isActive }) =>
                  `flex min-h-touch flex-1 flex-col items-center justify-center gap-0.5 px-1 py-2 text-[11px] font-medium ${
                    isActive ? 'text-brand-dark' : 'text-slate-500'
                  }`
                }
              >
                <ItemIcon className="h-5 w-5" aria-hidden="true" />
                <span className="truncate">{label}</span>
              </NavLink>
            ))}
          </nav>
        )}
      </div>
    </div>
  );
}
