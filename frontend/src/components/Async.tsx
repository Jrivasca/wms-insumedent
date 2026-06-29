import type { ReactNode } from 'react';

export function Loading({ label = 'Cargando…' }: { label?: string }) {
  return <div className="py-8 text-center text-sm text-slate-500">{label}</div>;
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
      <p>{message}</p>
      {onRetry && (
        <button onClick={onRetry} className="mt-2 underline">
          Reintentar
        </button>
      )}
    </div>
  );
}

export function Empty({ label = 'Sin resultados' }: { label?: string }) {
  return <div className="py-8 text-center text-sm text-slate-400">{label}</div>;
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
    <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 className="text-xl font-bold text-slate-900">{title}</h1>
        {subtitle && <p className="text-sm text-slate-500">{subtitle}</p>}
      </div>
      {actions && <div className="flex gap-2">{actions}</div>}
    </div>
  );
}
