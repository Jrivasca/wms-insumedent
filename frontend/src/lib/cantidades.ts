/**
 * Cantidades de bodega: siempre unidades ENTERAS.
 *
 * El backend ya las rechaza (esquemas de Pydantic), pero la pantalla tiene que avisar
 * antes de mandar: en la QA del 2026-09-29 los formularios enviaban -5, 0 y 1.5 y el
 * operario solo se enteraba por un error crudo del servidor.
 */

/** Devuelve el entero, o ``null`` si el texto no es una cantidad válida. */
export function unidadesEnteras(texto: string): number | null {
  const limpio = texto.trim();
  if (limpio === '') return null;
  const n = Number(limpio);
  if (!Number.isFinite(n) || !Number.isInteger(n)) return null;
  return n;
}

/**
 * Valida una cantidad a ingresar/mover. Devuelve el mensaje de error, o ``null`` si sirve.
 * ``maximo`` es el tope disponible (saldo del origen, lo empacado pendiente…).
 */
export function errorDeCantidad(
  texto: string,
  opciones: { maximo?: number; etiqueta?: string } = {}
): string | null {
  const { maximo, etiqueta = 'La cantidad' } = opciones;
  const n = unidadesEnteras(texto);
  if (n === null) return `${etiqueta} debe ser un número entero de unidades.`;
  if (n <= 0) return `${etiqueta} debe ser mayor que 0.`;
  if (maximo !== undefined && n > maximo) {
    return `${etiqueta} no puede superar ${maximo} ${maximo === 1 ? 'unidad' : 'unidades'}.`;
  }
  return null;
}

/** Igual que ``errorDeCantidad`` pero para ajustes: admite negativos y prohíbe el 0. */
export function errorDeCantidadDeAjuste(texto: string): string | null {
  const n = unidadesEnteras(texto);
  if (n === null) return 'La cantidad debe ser un número entero de unidades.';
  if (n === 0) return 'Un ajuste de 0 no cambia nada: indique cuánto agrega o descuenta.';
  return null;
}
