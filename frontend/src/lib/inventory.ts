/**
 * Presentación de los datos de inventario.
 *
 * Los valores internos no cambian: son los de `MovementType` en el backend.
 */
const MOVEMENT_LABELS: Record<string, string> = {
  receipt: 'Recepción',
  pick: 'Picking',
  pack: 'Packing',
  dispatch: 'Despacho',
  adjustment: 'Ajuste',
  transfer: 'Transferencia',
  count_adjustment: 'Ajuste por conteo',
  // Deja el WMS igual a Defontana; no viaja al ERP.
  reconciliation: 'Conciliación con ERP',
};

/** Tipo de movimiento en español; si es desconocido, se muestra el valor original. */
export function movementLabel(type?: string | null): string {
  if (!type) return '—';
  return MOVEMENT_LABELS[type] ?? type;
}
