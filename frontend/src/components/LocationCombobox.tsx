import { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, Loader2, MapPin, X } from 'lucide-react';
import { listLocations } from '../api/warehouses';
import type { Location } from '../types';

/**
 * Selector de ubicación con búsqueda.
 *
 * En bodega hay decenas de ubicaciones y un `<select>` obliga a recorrerlas todas.
 * Aquí se escribe parte del código (o del pasillo, rack o zona) y la lista se acota.
 *
 * La ubicación se acota a la bodega recibida: el endpoint `/locations` acepta
 * `warehouse_id`, así que cada pantalla ofrece solo ubicaciones de la bodega elegida.
 * Sin `warehouseId` se cargan todas (útil para filtrar); con `requireWarehouse` el
 * campo espera a que se elija bodega.
 */
export default function LocationCombobox({
  label,
  value,
  onChange,
  warehouseId,
  requireWarehouse = false,
  placeholder = 'Código, pasillo o zona…',
  hint,
  disabledIds,
  clearable = false,
}: {
  label: string;
  value: string;
  onChange: (locationId: string) => void;
  warehouseId?: string;
  /** El campo se bloquea hasta que haya bodega (formularios de movimiento). */
  requireWarehouse?: boolean;
  placeholder?: string;
  hint?: string;
  /** Ubicaciones que no se pueden elegir aquí (p. ej. el origen en una transferencia). */
  disabledIds?: string[];
  /** Permite volver a "sin ubicación" (filtros). */
  clearable?: boolean;
}) {
  const [all, setAll] = useState<Location[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [highlight, setHighlight] = useState(0);
  const boxRef = useRef<HTMLDivElement>(null);

  const waiting = requireWarehouse && !warehouseId;

  useEffect(() => {
    if (waiting) {
      setAll([]);
      return;
    }
    let alive = true;
    setLoading(true);
    setLoadError(null);
    listLocations(warehouseId || undefined)
      .then((ls) => {
        if (alive) setAll(ls.filter((l) => l.is_active !== false));
      })
      .catch(() => {
        if (alive) setLoadError('No se pudieron cargar las ubicaciones.');
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [warehouseId, waiting]);

  // Si la ubicación elegida no pertenece a la bodega actual, se descarta.
  useEffect(() => {
    if (!value || all.length === 0) return;
    if (!all.some((l) => l.id === value)) onChange('');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [all]);

  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [open]);

  const selected = all.find((l) => l.id === value) ?? null;

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const base = q
      ? all.filter((l) =>
          [l.code, l.name, l.zone, l.aisle, l.rack, l.level, l.bin]
            .filter(Boolean)
            .some((v) => String(v).toLowerCase().includes(q))
        )
      : all;
    return base.slice(0, 50);
  }, [all, query]);

  function describe(l: Location): string {
    const parts = [l.name, l.zone && `Zona ${l.zone}`, l.aisle && `Pasillo ${l.aisle}`, l.rack && `Rack ${l.rack}`];
    return parts.filter(Boolean).join(' · ');
  }

  function select(l: Location) {
    onChange(l.id);
    setQuery('');
    setOpen(false);
    setHighlight(0);
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setOpen(true);
      setHighlight((h) => Math.min(h + 1, Math.max(filtered.length - 1, 0)));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setHighlight((h) => Math.max(h - 1, 0));
    } else if (e.key === 'Enter') {
      const pick = filtered[highlight];
      if (open && pick && !disabledIds?.includes(pick.id)) {
        e.preventDefault();
        select(pick);
      }
    } else if (e.key === 'Escape') {
      setOpen(false);
    }
  }

  // Ubicación ya elegida: se muestra el código y se puede cambiar.
  if (selected) {
    return (
      <div>
        <label className="label">{label}</label>
        <div className="flex min-h-touch items-center justify-between gap-2 rounded-md border border-slate-300 bg-slate-50 px-3 py-2">
          <span className="flex min-w-0 items-center gap-2">
            <MapPin className="h-4 w-4 shrink-0 text-slate-400" aria-hidden="true" />
            <span className="min-w-0">
              <span className="code-strong block truncate">{selected.code}</span>
              {describe(selected) && (
                <span className="block truncate text-xs text-slate-500">{describe(selected)}</span>
              )}
            </span>
          </span>
          <button
            type="button"
            onClick={() => {
              onChange('');
              setQuery('');
              setOpen(true);
            }}
            className="shrink-0 text-xs font-medium text-brand hover:underline"
          >
            Cambiar
          </button>
        </div>
        {hint && <p className="hint">{hint}</p>}
      </div>
    );
  }

  return (
    <div ref={boxRef} className="relative">
      <label className="label" htmlFor={`loc-${label}`}>
        {label}
      </label>
      <MapPin
        className="pointer-events-none absolute left-3 top-[2.35rem] h-4 w-4 text-slate-400"
        aria-hidden="true"
      />
      <input
        id={`loc-${label}`}
        role="combobox"
        aria-expanded={open}
        aria-autocomplete="list"
        autoComplete="off"
        disabled={waiting}
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
          setHighlight(0);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
        className="input input-lg pl-9 pr-9 disabled:bg-slate-100 disabled:text-slate-400"
        placeholder={waiting ? 'Elige primero la bodega' : placeholder}
      />
      {query ? (
        <button
          type="button"
          onClick={() => {
            setQuery('');
            setHighlight(0);
          }}
          className="absolute right-2 top-[2rem] rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
          aria-label="Limpiar búsqueda"
        >
          <X className="h-4 w-4" />
        </button>
      ) : (
        <ChevronDown
          className="pointer-events-none absolute right-3 top-[2.35rem] h-4 w-4 text-slate-400"
          aria-hidden="true"
        />
      )}

      {loading && (
        <p className="hint flex items-center gap-1">
          <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
          Cargando ubicaciones…
        </p>
      )}
      {loadError && <p className="hint text-red-700">{loadError}</p>}
      {!loading && !loadError && !waiting && all.length === 0 && (
        <p className="hint text-amber-800">
          Esta bodega no tiene ubicaciones activas. Créalas en Administración · Ubicaciones.
        </p>
      )}
      {hint && !loading && <p className="hint">{hint}</p>}
      {clearable && value && (
        <button
          type="button"
          onClick={() => onChange('')}
          className="mt-1 text-xs font-medium text-brand hover:underline"
        >
          Quitar filtro de ubicación
        </button>
      )}

      {open && !waiting && filtered.length > 0 && (
        <ul
          role="listbox"
          className="absolute z-30 mt-1 max-h-64 w-full overflow-y-auto rounded-md border border-slate-200 bg-white shadow-raised"
        >
          {filtered.map((l, i) => {
            const isDisabled = disabledIds?.includes(l.id) ?? false;
            return (
              <li key={l.id} role="option" aria-selected={i === highlight}>
                <button
                  type="button"
                  disabled={isDisabled}
                  onMouseEnter={() => setHighlight(i)}
                  onClick={() => select(l)}
                  className={`flex min-h-touch w-full flex-col justify-center px-3 py-2 text-left ${
                    isDisabled
                      ? 'cursor-not-allowed text-slate-400'
                      : i === highlight
                        ? 'bg-brand-soft'
                        : 'hover:bg-slate-50'
                  }`}
                >
                  <span className="code-strong">{l.code}</span>
                  {describe(l) && <span className="text-xs text-slate-500">{describe(l)}</span>}
                  {isDisabled && <span className="text-xs">No disponible aquí</span>}
                </button>
              </li>
            );
          })}
        </ul>
      )}
      {open && !waiting && !loading && all.length > 0 && filtered.length === 0 && (
        <p className="hint">Ninguna ubicación coincide con «{query}».</p>
      )}
    </div>
  );
}
