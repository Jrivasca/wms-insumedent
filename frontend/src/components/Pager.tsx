/**
 * Offset pager. When `total` is provided it shows "X–Y de N" and enables "Next"
 * only while more rows remain; without it, it falls back to the heuristic of a
 * full page meaning there may be more.
 */
export default function Pager({
  offset,
  pageSize,
  count,
  total,
  onPrev,
  onNext,
}: {
  offset: number;
  pageSize: number;
  count: number;
  total?: number;
  onPrev: () => void;
  onNext: () => void;
}) {
  const from = count === 0 ? 0 : offset + 1;
  const to = offset + count;
  const hasPrev = offset > 0;
  const hasNext = total != null ? offset + count < total : count === pageSize;
  if (!hasPrev && !hasNext) return null; // single page → no controls

  return (
    <div className="mb-4 flex items-center justify-between text-sm">
      <span className="text-slate-500">
        {from}–{to}
        {total != null ? ` de ${total}` : ''}
      </span>
      <div className="flex gap-2">
        <button onClick={onPrev} disabled={!hasPrev} className="btn-secondary disabled:opacity-40">
          ‹ Anterior
        </button>
        <button onClick={onNext} disabled={!hasNext} className="btn-secondary disabled:opacity-40">
          Siguiente ›
        </button>
      </div>
    </div>
  );
}
