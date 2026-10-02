import { useEffect, useState } from 'react';

/**
 * Cantidad por escaneo: − / número / +. El número también se escribe (con 40 unidades,
 * tocar «+» 39 veces no es opción) y solo acepta dígitos: el teclado numérico del teléfono
 * igual deja pegar texto, así que se filtra al escribir, no solo con ``inputMode``.
 */
export default function QuantityStepper({
  id,
  value,
  onChange,
  max,
}: {
  id: string;
  value: number;
  onChange: (n: number) => void;
  /** Tope (p. ej. lo que falta de la línea). Sin tope, cualquier entero ≥ 1. */
  max?: number;
}) {
  // Texto aparte del número: mientras se escribe el campo puede quedar vacío un momento.
  const [text, setText] = useState(String(value));
  useEffect(() => setText(String(value)), [value]);

  const tope = max !== undefined ? Math.max(max, 1) : undefined;
  const clamp = (n: number) => Math.max(1, tope !== undefined ? Math.min(n, tope) : n);

  function escribir(raw: string) {
    const digitos = raw.replace(/\D/g, '').slice(0, 5);
    setText(digitos);
    if (digitos) onChange(clamp(parseInt(digitos, 10)));
  }

  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        onClick={() => onChange(clamp(value - 1))}
        disabled={value <= 1}
        className="btn-secondary h-touch w-touch text-xl disabled:opacity-40"
        aria-label="Restar uno"
      >
        −
      </button>
      <input
        id={id}
        type="text"
        inputMode="numeric"
        pattern="[0-9]*"
        autoComplete="off"
        value={text}
        onChange={(e) => escribir(e.target.value)}
        // Vacío o fuera de rango al salir: vuelve al valor válido vigente.
        onBlur={() => setText(String(value))}
        onFocus={(e) => e.target.select()}
        className="h-touch w-16 rounded-md border border-slate-300 bg-white text-center text-2xl font-bold tabular-nums outline-none focus:border-brand"
        aria-label="Cantidad por escaneo"
      />
      <button
        type="button"
        onClick={() => onChange(clamp(value + 1))}
        disabled={tope !== undefined && value >= tope}
        className="btn-secondary h-touch w-touch text-xl disabled:opacity-40"
        aria-label="Sumar uno"
      >
        +
      </button>
    </div>
  );
}
