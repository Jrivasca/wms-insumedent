import type { ComponentType, ReactNode } from 'react';
import { Link } from 'react-router-dom';

type Tone = 'neutral' | 'warn' | 'danger' | 'ok' | 'info';

const TONES: Record<Tone, { value: string; ring: string }> = {
  neutral: { value: 'text-slate-900', ring: '' },
  info: { value: 'text-brand-darker', ring: 'ring-1 ring-brand-border' },
  warn: { value: 'text-amber-900', ring: 'ring-1 ring-amber-300' },
  danger: { value: 'text-red-800', ring: 'ring-1 ring-red-300' },
  ok: { value: 'text-emerald-800', ring: 'ring-1 ring-emerald-300' },
};

/** Indicador compacto y legible. Si recibe `to`, es clicable y lleva al detalle. */
export default function MetricCard({
  label,
  value,
  hint,
  tone = 'neutral',
  icon: Icon,
  to,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  tone?: Tone;
  icon?: ComponentType<{ className?: string }>;
  to?: string;
}) {
  const styles = TONES[tone];
  const content = (
    <>
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</p>
        {Icon && <Icon className="h-4 w-4 text-slate-400" />}
      </div>
      <p className={`mt-1 text-2xl font-bold tabular-nums ${styles.value}`}>{value}</p>
      {hint && <p className="mt-0.5 text-xs text-slate-500">{hint}</p>}
    </>
  );

  if (to) {
    return (
      <Link to={to} className={`card block transition hover:shadow-raised ${styles.ring}`}>
        {content}
      </Link>
    );
  }
  return <div className={`card ${styles.ring}`}>{content}</div>;
}
