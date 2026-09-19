import type { ReactNode } from 'react';
import { AlertTriangle, Inbox, Loader2, RotateCcw } from 'lucide-react';

/** Carga: spinner discreto con texto (no bloquea la lectura del resto de la pantalla). */
export function Loading({ label = 'Cargando…' }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-10 text-sm text-slate-500" role="status">
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
      {label}
    </div>
  );
}

/** Esqueleto para tablas y listas mientras llegan los datos. */
export function LoadingRows({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-2" role="status" aria-label="Cargando">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-11 animate-pulse rounded-md bg-slate-200/70" />
      ))}
    </div>
  );
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div
      className="mb-4 flex items-start gap-3 rounded-card border border-red-200 bg-red-50 p-3 text-sm text-red-800"
      role="alert"
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <p>{message}</p>
        {onRetry && (
          <button onClick={onRetry} className="btn-secondary btn-sm mt-2">
            <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
            Reintentar
          </button>
        )}
      </div>
    </div>
  );
}

/** Vacío: dice qué falta y, si corresponde, ofrece la acción para avanzar. */
export function Empty({
  label = 'Sin resultados',
  hint,
  action,
}: {
  label?: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <div className="rounded-card border border-dashed border-slate-300 bg-white/60 px-4 py-10 text-center">
      <Inbox className="mx-auto h-6 w-6 text-slate-400" aria-hidden="true" />
      <p className="mt-2 text-sm font-medium text-slate-600">{label}</p>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
      {action && <div className="mt-3 flex justify-center">{action}</div>}
    </div>
  );
}

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-xl font-bold tracking-tight text-slate-900">{title}</h1>
        {subtitle && <p className="mt-0.5 text-sm text-slate-500">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}
