// Modelo de permisos por rol.
//
// admin y supervisor tienen acceso completo. Los demás roles cubren un tramo del
// flujo: ventas crea pedidos, bodega hace picking/packing, despacho confirma envíos.

export const FULL_ACCESS = ['admin', 'supervisor'];

/** ¿El rol puede entrar a una sección abierta a `allowed`? admin/supervisor entran a todo. */
export function can(role: string | undefined, allowed?: string[]): boolean {
  if (!role) return false;
  if (FULL_ACCESS.includes(role)) return true;
  return (allowed ?? []).includes(role);
}

/** Página donde aterriza cada rol al entrar (o si le rebotan de una sección). */
export const ROLE_HOME: Record<string, string> = {
  sales: '/orders',
  dispatcher: '/dispatch',
  picker: '/my/picking',
  packer: '/my/packing',
  receiver: '/inventory/recepcion',
};

export function homeFor(role: string | undefined): string {
  return (role && ROLE_HOME[role]) || '/';
}

/** Roles ofrecidos al crear usuarios, con nombre entendible. */
export const ROLE_OPTIONS = [
  { value: 'admin', label: 'Administrador (todo)' },
  { value: 'supervisor', label: 'Supervisor (todo + aprobaciones)' },
  { value: 'sales', label: 'Ventas (crea pedidos)' },
  { value: 'picker', label: 'Bodega (picking y packing)' },
  { value: 'dispatcher', label: 'Despacho (confirma envíos)' },
];

export const ROLE_LABEL: Record<string, string> = Object.fromEntries(
  ROLE_OPTIONS.map((r) => [r.value, r.label])
);

/** Roles de piso: operan tareas asignadas de picking/packing. */
export const FLOOR_ROLES = ['picker', 'packer', 'receiver'];
