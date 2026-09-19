/** Avance de una tarea o pedido: barra + conteo, sin depender solo del color. */
export default function ProgressBar({
  value,
  total,
  unit,
  compact = false,
}: {
  value: number;
  total: number;
  unit?: string;
  compact?: boolean;
}) {
  const safeTotal = total > 0 ? total : 0;
  const percent = safeTotal === 0 ? 0 : Math.min(100, Math.round((value / safeTotal) * 100));
  const done = safeTotal > 0 && value >= safeTotal;

  return (
    <div className="min-w-[6rem]">
      <div
        className="h-1.5 w-full overflow-hidden rounded-full bg-slate-200"
        role="progressbar"
        aria-valuenow={percent}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className={`h-full rounded-full transition-[width] ${done ? 'bg-emerald-500' : 'bg-brand'}`}
          style={{ width: `${percent}%` }}
        />
      </div>
      {!compact && (
        <p className="mt-1 text-xs tabular-nums text-slate-500">
          {value}/{safeTotal} {unit ?? ''} · {percent}%
        </p>
      )}
    </div>
  );
}
