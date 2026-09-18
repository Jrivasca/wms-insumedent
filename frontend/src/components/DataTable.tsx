import type { ReactNode } from 'react';

export interface Column<T> {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
  align?: 'left' | 'right';
  /** Se oculta en tablet para no comprimir la tabla. */
  secondary?: boolean;
  width?: string;
}

/**
 * Tabla densa para escritorio. En móvil NO se comprime: las pantallas usan
 * :MobileCardList con la misma información priorizada.
 */
export default function DataTable<T>({
  columns,
  rows,
  keyOf,
  onRowClick,
  className = '',
}: {
  columns: Column<T>[];
  rows: T[];
  keyOf: (row: T) => string;
  onRowClick?: (row: T) => void;
  className?: string;
}) {
  return (
    <div className={`card-flush overflow-x-auto ${className}`}>
      <table className="table w-full">
        <thead className="border-b border-slate-200 bg-slate-50">
          <tr>
            {columns.map((c) => (
              <th
                key={c.key}
                style={c.width ? { width: c.width } : undefined}
                className={`${c.align === 'right' ? 'text-right' : ''} ${
                  c.secondary ? 'hidden lg:table-cell' : ''
                }`}
              >
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((row) => (
            <tr
              key={keyOf(row)}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              className={onRowClick ? 'cursor-pointer' : undefined}
            >
              {columns.map((c) => (
                <td
                  key={c.key}
                  className={`${c.align === 'right' ? 'text-right tabular-nums' : ''} ${
                    c.secondary ? 'hidden lg:table-cell' : ''
                  }`}
                >
                  {c.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Lista de tarjetas: la alternativa móvil de cualquier tabla. */
export function MobileCardList<T>({
  rows,
  keyOf,
  render,
}: {
  rows: T[];
  keyOf: (row: T) => string;
  render: (row: T) => ReactNode;
}) {
  return (
    <div className="space-y-2">
      {rows.map((row) => (
        <div key={keyOf(row)} className="card">
          {render(row)}
        </div>
      ))}
    </div>
  );
}
