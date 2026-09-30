/** Cantidad para mostrar: entero si no tiene decimales (2 en vez de 2.0), si no hasta 2 decimales. */
export function fmtQty(value: number | null | undefined): string {
  const n = Number(value ?? 0);
  if (!Number.isFinite(n)) return '0';
  return Number.isInteger(n) ? String(n) : String(Number(n.toFixed(2)));
}

/** Fecha de Defontana (ISO "2026-07-27T00:00:00") → "27-07-2026". Vacío/ inválido → "—". */
export function fmtDate(value: string | Date | null | undefined): string {
  if (!value) return '—';
  const d = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(d.getTime())) return '—';
  const dd = String(d.getDate()).padStart(2, '0');
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  return `${dd}-${mm}-${d.getFullYear()}`;
}
