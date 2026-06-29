const COLORS: Record<string, string> = {
  // generic
  ok: 'bg-emerald-100 text-emerald-800',
  active: 'bg-emerald-100 text-emerald-800',
  connected: 'bg-emerald-100 text-emerald-800',
  completed: 'bg-emerald-100 text-emerald-800',
  done: 'bg-emerald-100 text-emerald-800',
  packed: 'bg-emerald-100 text-emerald-800',
  picked: 'bg-emerald-100 text-emerald-800',
  dispatched: 'bg-emerald-100 text-emerald-800',
  success: 'bg-emerald-100 text-emerald-800',

  pending: 'bg-amber-100 text-amber-800',
  in_progress: 'bg-blue-100 text-blue-800',
  picking: 'bg-blue-100 text-blue-800',
  packing: 'bg-blue-100 text-blue-800',
  running: 'bg-blue-100 text-blue-800',
  queued: 'bg-amber-100 text-amber-800',
  ready_to_dispatch: 'bg-indigo-100 text-indigo-800',
  retrying: 'bg-amber-100 text-amber-800',

  partial: 'bg-orange-100 text-orange-800',
  missing: 'bg-red-100 text-red-800',
  rejected: 'bg-red-100 text-red-800',
  failed: 'bg-red-100 text-red-800',
  error: 'bg-red-100 text-red-800',
  cancelled: 'bg-slate-200 text-slate-600',
  disconnected: 'bg-red-100 text-red-800',
  inactive: 'bg-slate-200 text-slate-600',
};

export default function StatusBadge({ status }: { status?: string }) {
  const key = (status ?? 'unknown').toLowerCase();
  const cls = COLORS[key] ?? 'bg-slate-100 text-slate-700';
  return <span className={`badge ${cls}`}>{status ?? '—'}</span>;
}
