// Etiquetas en rollo de varias columnas (perfil Zebra ZD220, 3 × 30 × 10 mm).
//
// Todo lo que decide dónde cae la tinta está acá, en funciones puras, para que la vista
// previa, la impresión por navegador y el ZPL usen exactamente la misma geometría. Las
// medidas van en milímetros; las posiciones se ajustan a la grilla de puntos de la
// impresora (203 dpi = 8 puntos/mm, como la trata Zebra): una barra de 0,25 mm tiene que
// caer en 2 puntos enteros, no en 1,9 que el controlador redondea a 1 o a 3.

export const DOTS_PER_MM = 8;

/** Redondea a la grilla de puntos de la impresora. */
export function snapMm(mm: number): number {
  return Math.round(mm * DOTS_PER_MM) / DOTS_PER_MM;
}

export function mmToDots(mm: number): number {
  return Math.round(mm * DOTS_PER_MM);
}

export interface RollProfile {
  /** Ancho total del papel (de borde a borde del liner). */
  paperWidthMm: number;
  labelWidthMm: number;
  labelHeightMm: number;
  columns: number;
  /** Del borde izquierdo del papel a la primera etiqueta. */
  marginLeftMm: number;
  /** De la última etiqueta al borde derecho del papel. */
  marginRightMm: number;
  /** Entre columnas. */
  gapXMm: number;
  /**
   * Entre filas. No entra en la geometría impresa: cada fila es una página (o un formato
   * ZPL) del alto de la etiqueta y el avance hasta la siguiente lo detecta la impresora por
   * el espacio entre etiquetas. Se guarda para dejar la medida registrada y dibujarla en
   * la vista previa.
   */
  gapYMm: number;
  /** Ajuste fino de calibración: corre el contenido de todas las columnas. */
  offsetXMm: number;
  offsetYMm: number;
}

export const ZEBRA_ZD220_3X_NAME = 'Zebra ZD220 — 3 columnas — 30 × 10 mm';

// 95 mm salió de una medición con regla y es provisional. Los márgenes y la separación
// entre columnas NO están medidos: el default reparte parejo los 5 mm que sobran
// (95 − 3 × 30) en dos márgenes y dos separaciones. Es un punto de partida para la prueba
// de alineación, no una medida.
export const ZEBRA_ZD220_3X_DEFAULT: RollProfile = {
  paperWidthMm: 95,
  labelWidthMm: 30,
  labelHeightMm: 10,
  columns: 3,
  marginLeftMm: 1.25,
  marginRightMm: 1.25,
  gapXMm: 1.25,
  gapYMm: 0,
  offsetXMm: 0,
  offsetYMm: 0,
};

/** Lo que sobra (positivo) o falta (negativo) para llenar el ancho del papel. */
export function widthSlackMm(p: RollProfile): number {
  const used =
    p.marginLeftMm + p.marginRightMm + p.columns * p.labelWidthMm + (p.columns - 1) * p.gapXMm;
  return Math.round((p.paperWidthMm - used) * 1000) / 1000;
}

// ZD220: cabezal de 104 mm a 203 dpi (832 puntos). Más ancho no se puede imprimir.
const MAX_PRINT_WIDTH_MM = 104;
// Diferencia tolerada entre la suma de medidas y el ancho del papel: menos que eso es error
// de regla; más, alguna medida está mal.
const SLACK_TOLERANCE_MM = 0.5;

export interface ProfileCheck {
  errors: string[];
  warnings: string[];
}

export function checkProfile(p: RollProfile): ProfileCheck {
  const errors: string[] = [];
  const warnings: string[] = [];
  const nums: [string, number][] = [
    ['ancho del papel', p.paperWidthMm],
    ['ancho de etiqueta', p.labelWidthMm],
    ['alto de etiqueta', p.labelHeightMm],
    ['margen izquierdo', p.marginLeftMm],
    ['margen derecho', p.marginRightMm],
    ['separación entre columnas', p.gapXMm],
    ['separación entre filas', p.gapYMm],
  ];
  for (const [name, v] of nums) {
    if (!Number.isFinite(v) || v < 0) errors.push(`El ${name} debe ser un número mayor o igual a cero.`);
  }
  if (!Number.isInteger(p.columns) || p.columns < 1) {
    errors.push('El número de columnas debe ser un entero mayor que cero.');
  }
  if (p.labelWidthMm <= 0 || p.labelHeightMm <= 0 || p.paperWidthMm <= 0) {
    errors.push('El papel y la etiqueta deben tener medidas mayores que cero.');
  }
  if (errors.length) return { errors, warnings };

  if (p.paperWidthMm > MAX_PRINT_WIDTH_MM) {
    errors.push(`El papel mide ${p.paperWidthMm} mm y la ZD220 imprime hasta ${MAX_PRINT_WIDTH_MM} mm.`);
  }
  const slack = widthSlackMm(p);
  if (slack < -0.001) {
    errors.push(
      `Las etiquetas, separaciones y márgenes suman ${fmtMm(p.paperWidthMm - slack)} mm y no caben ` +
        `en los ${fmtMm(p.paperWidthMm)} mm del papel (sobran ${fmtMm(-slack)} mm).`
    );
  } else if (slack > SLACK_TOLERANCE_MM) {
    warnings.push(
      `Las medidas suman ${fmtMm(p.paperWidthMm - slack)} mm y el papel mide ${fmtMm(p.paperWidthMm)} mm: ` +
        `faltan ${fmtMm(slack)} mm por asignar. Revise los márgenes o la separación.`
    );
  }
  // Más de 2 mm de ajuste ya no es calibración fina: alguna medida (o el formato del
  // controlador) está mal y conviene corregirla en su origen.
  if (Math.abs(p.offsetXMm) > 2 || Math.abs(p.offsetYMm) > 2) {
    warnings.push('El ajuste fino supera 2 mm: revise las medidas o el formato del controlador.');
  }
  const t = template(p);
  if (!t.fits) errors.push(t.reason);
  return { errors, warnings };
}

export function fmtMm(mm: number): string {
  return (Math.round(mm * 100) / 100).toLocaleString('es-CL', { maximumFractionDigits: 2 });
}

// ---------------------------------------------------------------------------
// Plantilla de contenido: código EAN-13 + SKU legible, nada más (no cabe el nombre).
// ---------------------------------------------------------------------------

/** Ancho de módulo: 2 puntos. 1 punto (0,125 mm) no lo resuelve bien un cabezal térmico. */
export const MODULE_MM = 0.25;
const EAN_MODULES = 95;
// Zonas de silencio mínimas de EAN-13 (GS1): 11 módulos a la izquierda, 7 a la derecha.
const QUIET_LEFT_MODULES = 11;
const QUIET_RIGHT_MODULES = 7;
export const BARCODE_WIDTH_MM = EAN_MODULES * MODULE_MM; // 23,75 mm

const PAD_TOP_MM = 0.75;
const PAD_BOTTOM_MM = 0.75;
const TEXT_GAP_MM = 0.25;
/** Alto de la línea del SKU (tamaño de fuente). Monoespaciada: cada carácter ocupa 0,6 em. */
export const TEXT_HEIGHT_MM = 2.125;
const CHAR_ADVANCE_EM = 0.6;
/** Debajo de esto el escáner deja de leer de forma confiable un EAN truncado. */
const MIN_BAR_HEIGHT_MM = 4;

export interface Template {
  fits: boolean;
  reason: string;
  barcodeLeftMm: number;
  barcodeTopMm: number;
  barHeightMm: number;
  textTopMm: number;
  maxTextChars: number;
}

export function template(p: Pick<RollProfile, 'labelWidthMm' | 'labelHeightMm'>): Template {
  const quietTotal = (QUIET_LEFT_MODULES + QUIET_RIGHT_MODULES) * MODULE_MM;
  const needWidth = BARCODE_WIDTH_MM + quietTotal;
  // Centrado: los dos lados quedan con la misma zona de silencio, mayor que la mínima.
  const barcodeLeftMm = snapMm((p.labelWidthMm - BARCODE_WIDTH_MM) / 2);
  const barHeightMm = snapMm(
    p.labelHeightMm - PAD_TOP_MM - TEXT_GAP_MM - TEXT_HEIGHT_MM - PAD_BOTTOM_MM
  );
  const maxTextChars = Math.floor((p.labelWidthMm - 1) / (TEXT_HEIGHT_MM * CHAR_ADVANCE_EM));
  const base = {
    barcodeLeftMm,
    barcodeTopMm: PAD_TOP_MM,
    barHeightMm,
    textTopMm: snapMm(PAD_TOP_MM + barHeightMm + TEXT_GAP_MM),
    maxTextChars,
  };
  if (p.labelWidthMm < needWidth) {
    return {
      ...base,
      fits: false,
      reason:
        `El código EAN-13 con sus zonas de silencio necesita ${fmtMm(needWidth)} mm de ancho y ` +
        `la etiqueta mide ${fmtMm(p.labelWidthMm)} mm. No se achica el código: no se leería.`,
    };
  }
  if (barHeightMm < MIN_BAR_HEIGHT_MM) {
    return {
      ...base,
      fits: false,
      reason:
        `Con ${fmtMm(p.labelHeightMm)} mm de alto las barras quedarían de ${fmtMm(barHeightMm)} mm; ` +
        `se necesitan al menos ${fmtMm(MIN_BAR_HEIGHT_MM)} mm.`,
    };
  }
  return { ...base, fits: true, reason: '' };
}

// ---------------------------------------------------------------------------
// Ítems y filas
// ---------------------------------------------------------------------------

export function isValidEan13(code: string): boolean {
  if (!/^\d{13}$/.test(code)) return false;
  const total = code
    .slice(0, 12)
    .split('')
    .reduce((acc, c, i) => acc + (i % 2 ? 3 : 1) * Number(c), 0);
  return (10 - (total % 10)) % 10 === Number(code[12]);
}

export interface RollItem {
  key: string;
  sku: string;
  barcode: string;
}

export interface RollRequest {
  productId: string;
  sku: string;
  barcode: string;
  quantity: number;
}

export interface Rejected {
  sku: string;
  reason: string;
}

/**
 * Expande las cantidades en etiquetas, en el orden pedido y cada producto seguido, y deja
 * fuera lo que no se puede imprimir bien en esta plantilla, diciendo por qué. No se trunca
 * ni se achica nada para forzarlo a caber.
 */
export function expandItems(
  requests: RollRequest[],
  maxTextChars: number
): { items: RollItem[]; rejected: Rejected[] } {
  const items: RollItem[] = [];
  const rejected: Rejected[] = [];
  for (const r of requests) {
    const qty = Math.floor(r.quantity);
    if (!(qty > 0)) continue;
    if (!r.barcode) {
      rejected.push({ sku: r.sku, reason: 'no tiene código de barras' });
      continue;
    }
    if (!isValidEan13(r.barcode)) {
      rejected.push({
        sku: r.sku,
        reason: `su código «${r.barcode}» no es un EAN-13 válido, y en 30 mm solo cabe un EAN-13`,
      });
      continue;
    }
    if (r.sku.length > maxTextChars) {
      rejected.push({
        sku: r.sku,
        reason: `el SKU tiene ${r.sku.length} caracteres y en la etiqueta caben ${maxTextChars}`,
      });
      continue;
    }
    for (let i = 0; i < qty; i++) {
      items.push({ key: `${r.productId}-${i}`, sku: r.sku, barcode: r.barcode });
    }
  }
  return { items, rejected };
}

/** Filas de `columns`; la última se completa con huecos (`null`) para no correr posiciones. */
export function toRows<T>(items: T[], columns: number): (T | null)[][] {
  const rows: (T | null)[][] = [];
  if (!Number.isInteger(columns) || columns < 1) return rows;
  for (let i = 0; i < items.length; i += columns) {
    const row: (T | null)[] = items.slice(i, i + columns);
    while (row.length < columns) row.push(null);
    rows.push(row);
  }
  return rows;
}

/** Borde izquierdo de cada columna, en mm desde el borde del papel, ya en la grilla. */
export function columnLeftsMm(p: RollProfile): number[] {
  return Array.from({ length: p.columns }, (_, c) =>
    snapMm(p.marginLeftMm + c * (p.labelWidthMm + p.gapXMm) + p.offsetXMm)
  );
}

// ---------------------------------------------------------------------------
// ZPL (203 dpi)
// ---------------------------------------------------------------------------

/** Texto para ^FD con ^FH: todo lo que no sea alfanumérico va en hexadecimal (UTF-8). */
function zplText(text: string): string {
  let out = '';
  for (const ch of text) {
    if (/[A-Za-z0-9 .-]/.test(ch)) out += ch;
    else for (const b of new TextEncoder().encode(ch)) out += `_${b.toString(16).toUpperCase().padStart(2, '0')}`;
  }
  return out;
}

/**
 * Un formato ZPL por fila. ^PW/^LL fijan la fila al ancho del papel y al alto de la
 * etiqueta; el avance entre filas lo pone la impresora con su sensor de espacio.
 */
export function buildZpl(rows: (RollItem | string | null)[][], p: RollProfile): string {
  const t = template(p);
  const lefts = columnLeftsMm(p);
  const labelW = mmToDots(p.labelWidthMm);
  const top = mmToDots(p.offsetYMm);
  const fontH = mmToDots(TEXT_HEIGHT_MM);
  const out: string[] = [];
  for (const row of rows) {
    const cmds = [
      '^XA',
      '^CI28',
      `^PW${mmToDots(p.paperWidthMm)}`,
      `^LL${mmToDots(p.labelHeightMm)}`,
      '^LH0,0',
    ];
    row.forEach((cell, c) => {
      if (cell === null) return;
      const x = mmToDots(lefts[c]);
      if (typeof cell === 'string') {
        // Prueba de alineación: el texto centrado y un marco 0,5 mm adentro del borde.
        const inset = mmToDots(0.5);
        const h = mmToDots(p.labelHeightMm) - 2 * inset;
        cmds.push(`^FO${x + inset},${top + inset}^GB${labelW - 2 * inset},${h},2^FS`);
        cmds.push(
          `^FO${x},${top + Math.round((mmToDots(p.labelHeightMm) - 24) / 2)}` +
            `^A0N,24,20^FB${labelW},1,0,C^FH^FD${zplText(cell)}^FS`
        );
        return;
      }
      // ^BE recibe los 12 dígitos y calcula el verificador; el 13° ya se validó antes.
      cmds.push(
        `^FO${x + mmToDots(t.barcodeLeftMm)},${top + mmToDots(t.barcodeTopMm)}` +
          `^BY${mmToDots(MODULE_MM)}^BEN,${mmToDots(t.barHeightMm)},N,N^FD${cell.barcode.slice(0, 12)}^FS`
      );
      cmds.push(
        `^FO${x},${top + mmToDots(t.textTopMm)}^A0N,${fontH},${Math.round(fontH * 0.8)}` +
          `^FB${labelW},1,0,C^FH^FD${zplText(cell.sku)}^FS`
      );
    });
    cmds.push('^PQ1', '^XZ');
    out.push(cmds.join('\n'));
  }
  return out.join('\n') + '\n';
}

