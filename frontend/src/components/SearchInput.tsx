import { Search, X } from 'lucide-react';

/** Buscador de una pantalla (no es el buscador global: cada pantalla filtra lo suyo). */
export default function SearchInput({
  value,
  onChange,
  onSubmit,
  placeholder = 'Buscar…',
  label,
}: {
  value: string;
  onChange: (value: string) => void;
  onSubmit?: () => void;
  placeholder?: string;
  label?: string;
}) {
  return (
    <div className="relative">
      {label && <label className="label">{label}</label>}
      <Search
        className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400"
        aria-hidden="true"
        style={label ? { top: 'calc(50% + 0.75rem)' } : undefined}
      />
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && onSubmit) {
            e.preventDefault();
            onSubmit();
          }
        }}
        className="input pl-9 pr-9"
        placeholder={placeholder}
        aria-label={label ?? placeholder}
      />
      {value && (
        <button
          type="button"
          onClick={() => {
            onChange('');
            onSubmit?.();
          }}
          className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
          style={label ? { top: 'calc(50% + 0.75rem)' } : undefined}
          aria-label="Limpiar búsqueda"
        >
          <X className="h-4 w-4" />
        </button>
      )}
    </div>
  );
}
