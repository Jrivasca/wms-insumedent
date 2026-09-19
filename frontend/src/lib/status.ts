/**
 * Traducción y color de los estados del sistema.
 *
 * Los valores internos (los que viajan al backend) NO cambian: esto es solo presentación.
 * Cada estado tiene un tono con significado: ámbar = requiere atención, rojo = error o
 * bloqueo, verde = correcto, cian/azul = en curso, gris = inactivo.
 */
export type StatusTone = 'neutral' | 'progress' | 'ok' | 'warn' | 'danger' | 'info';

const LABELS: Record<string, string> = {
  // Pedidos
  imported: 'Importado',
  pending_picking: 'Por pickear',
  picking: 'En picking',
  picked: 'Pickeado',
  packing: 'En packing',
  packed: 'Empacado',
  ready_to_dispatch: 'Listo para despacho',
  partially_dispatched: 'Despacho parcial',
  dispatched: 'Despachado',
  sync_error: 'Error de sincronización',
  cancelled: 'Cancelado',
  // Cumplimiento del pedido
  complete: 'Completo',
  partial: 'Parcial',
  // Tareas de picking / packing
  pending: 'Pendiente',
  assigned: 'Asignada',
  in_progress: 'En curso',
  paused: 'Pausada',
  completed: 'Completado',
  completed_with_differences: 'Completado con diferencias',
  observed: 'Con observaciones',
  // Líneas
  missing: 'Faltante',
  // Despachos y cola de sincronización
  processing: 'Procesando',
  retrying: 'Reintentando',
  success: 'Correcto',
  failed: 'Falló',
  error: 'Error',
  queued: 'En cola',
  // Conexión con el ERP
  not_configured: 'Sin configurar',
  configured: 'Configurado',
  connected: 'Conectado',
  disconnected: 'Sin conexión',
  disabled: 'Deshabilitado',
  mock: 'Entorno de prueba',
  test: 'Pruebas',
  production: 'Producción',
  // Genéricos
  active: 'Activo',
  inactive: 'Inactivo',
  ok: 'Correcto',
  rejected: 'Rechazado',
  unknown: 'Desconocido',
};

const TONES: Record<string, StatusTone> = {
  imported: 'neutral',
  pending_picking: 'warn',
  picking: 'progress',
  picked: 'progress',
  packing: 'progress',
  packed: 'progress',
  ready_to_dispatch: 'info',
  partially_dispatched: 'warn',
  dispatched: 'ok',
  sync_error: 'danger',
  cancelled: 'neutral',
  complete: 'ok',
  partial: 'warn',
  pending: 'warn',
  assigned: 'info',
  in_progress: 'progress',
  paused: 'warn',
  completed: 'ok',
  completed_with_differences: 'warn',
  observed: 'warn',
  missing: 'danger',
  processing: 'progress',
  retrying: 'warn',
  success: 'ok',
  failed: 'danger',
  error: 'danger',
  queued: 'warn',
  not_configured: 'neutral',
  configured: 'info',
  connected: 'ok',
  disconnected: 'danger',
  disabled: 'neutral',
  mock: 'neutral',
  test: 'info',
  production: 'ok',
  active: 'ok',
  inactive: 'neutral',
  ok: 'ok',
  rejected: 'danger',
  unknown: 'neutral',
};

export const TONE_CLASSES: Record<StatusTone, string> = {
  neutral: 'bg-slate-100 text-slate-700',
  info: 'bg-brand-soft text-brand-darker',
  progress: 'bg-sky-100 text-sky-800',
  ok: 'bg-emerald-100 text-emerald-800',
  warn: 'bg-amber-100 text-amber-900',
  danger: 'bg-red-100 text-red-800',
};

/** Punto de color (para listas compactas donde no cabe el badge completo). */
export const TONE_DOTS: Record<StatusTone, string> = {
  neutral: 'bg-slate-400',
  info: 'bg-brand',
  progress: 'bg-sky-500',
  ok: 'bg-emerald-500',
  warn: 'bg-amber-500',
  danger: 'bg-red-500',
};

function key(status?: string | null): string {
  // Los estados de Defontana llegan como "EEX (EN_DESPACHO_EN_FACTURACION)": se respeta tal cual.
  return (status ?? 'unknown').toString().trim().toLowerCase();
}

/** Etiqueta en español; si el estado es desconocido, se muestra el valor original. */
export function statusLabel(status?: string | null): string {
  if (!status) return LABELS.unknown;
  return LABELS[key(status)] ?? status;
}

export function statusTone(status?: string | null): StatusTone {
  return TONES[key(status)] ?? 'neutral';
}

export function statusClasses(status?: string | null): string {
  return TONE_CLASSES[statusTone(status)];
}
