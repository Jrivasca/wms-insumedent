/** Simple offset pager. "Next" is enabled while a full page came back. */
export default function Pager({
  offset,
  pageSize,
  count,
  onPrev,
  onNext,
}: {
  offset: number;
  pageSize: number;
  count: number;
  onPrev: () => void;
  onNext: () => void;
}) {
  const from = count === 0 ? 0 : offset + 1;
  const to = offset + count;
  const hasPrev = offset > 0;
  const hasNext = count === pageSize;
  if (!hasPrev && !hasNext) return null; // single page → no controls

  return (
    <div className="mb-4 flex items-center justify-between text-sm">
      <span className="text-slate-500">
        {from}–{to}
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
