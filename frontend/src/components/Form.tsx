import { useState } from 'react';
import { listProducts } from '../api/products';
import type { Product } from '../types';

export function Field({
  label,
  value,
  onChange,
  type = 'text',
  required,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  required?: boolean;
  placeholder?: string;
}) {
  return (
    <div>
      <label className="label">{label}</label>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="input"
        required={required}
        placeholder={placeholder}
      />
    </div>
  );
}

export function SelectField({
  label,
  value,
  onChange,
  options,
  required,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  required?: boolean;
}) {
  return (
    <div>
      <label className="label">{label}</label>
      <select value={value} onChange={(e) => onChange(e.target.value)} className="input" required={required}>
        <option value="">Seleccione…</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}

/** Search-and-pick a product (avoids typing raw product IDs). */
export function ProductPicker({
  value,
  onChange,
}: {
  value: Product | null;
  onChange: (p: Product | null) => void;
}) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<Product[]>([]);
  const [searching, setSearching] = useState(false);

  async function search(q: string) {
    setQuery(q);
    if (q.trim().length < 2) {
      setResults([]);
      return;
    }
    setSearching(true);
    try {
      setResults((await listProducts(q.trim(), 8, 0)).items);
    } catch {
      setResults([]);
    } finally {
      setSearching(false);
    }
  }

  if (value) {
    return (
      <div>
        <label className="label">Producto</label>
        <div className="flex min-h-touch items-center justify-between gap-2 rounded-md border border-slate-300 bg-slate-50 px-3 py-2">
          <div className="min-w-0">
            <div className="truncate font-medium">{value.name}</div>
            <div className="code">{value.sku}</div>
          </div>
          <button type="button" onClick={() => onChange(null)} className="text-xs font-medium text-brand underline">
            Cambiar
          </button>
        </div>
      </div>
    );
  }

  return (
    <div>
      <label className="label">Producto</label>
      <input
        value={query}
        onChange={(e) => search(e.target.value)}
        placeholder="Buscar por nombre o SKU…"
        className="input"
      />
      {searching && <div className="mt-1 text-xs text-slate-400">Buscando…</div>}
      {results.length > 0 && (
        <div className="mt-1 max-h-48 overflow-y-auto rounded-md border border-slate-200 bg-white shadow-raised">
          {results.map((p) => (
            <button
              type="button"
              key={p.id}
              onClick={() => {
                onChange(p);
                setQuery('');
                setResults([]);
              }}
              className="block min-h-touch w-full px-3 py-2 text-left text-sm hover:bg-brand-soft"
            >
              <span className="font-medium">{p.name}</span>{' '}
              <span className="code">· {p.sku}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
