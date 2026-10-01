import { createPortal } from 'react-dom';
import { ean13Bits } from './EanBarcode';
import {
  BARCODE_WIDTH_MM,
  TEXT_HEIGHT_MM,
  columnLeftsMm,
  snapMm,
  template,
  type RollItem,
  type RollProfile,
} from '../lib/labelRoll';

// Una celda es una etiqueta de producto, un texto de la prueba de alineación o un hueco.
export type RollCell = RollItem | string | null;

/** EAN-13 en milímetros: cada módulo mide exactamente MODULE_MM, sin escalar. */
function BarcodeMm({ code, heightMm }: { code: string; heightMm: number }) {
  const bits = ean13Bits(code);
  if (!bits) return null;
  // Barras contiguas en un solo rectángulo: sin costuras entre módulos al rasterizar.
  const bars: { x: number; w: number }[] = [];
  for (let i = 0; i < bits.length; i++) {
    if (bits[i] !== '1') continue;
    const last = bars[bars.length - 1];
    if (last && last.x + last.w === i) last.w += 1;
    else bars.push({ x: i, w: 1 });
  }
  return (
    <svg
      width={`${BARCODE_WIDTH_MM}mm`}
      height={`${heightMm}mm`}
      viewBox={`0 0 ${bits.length} 1`}
      preserveAspectRatio="none"
      shapeRendering="crispEdges"
      role="img"
      aria-label={`Código de barras ${code}`}
      style={{ display: 'block' }}
    >
      {bars.map((b) => (
        <rect key={b.x} x={b.x} y={0} width={b.w} height={1} fill="#000" />
      ))}
    </svg>
  );
}

function Cell({ cell, profile }: { cell: RollCell; profile: RollProfile }) {
  if (cell === null) return null;
  const t = template(profile);
  if (typeof cell === 'string') {
    return (
      <div
        style={{
          position: 'absolute',
          inset: '0.5mm',
          border: '0.25mm solid #000',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontFamily: 'Arial, Helvetica, sans-serif',
          fontWeight: 700,
          fontSize: '2.5mm',
          lineHeight: 1,
          color: '#000',
        }}
      >
        {cell}
      </div>
    );
  }
  return (
    <>
      <div style={{ position: 'absolute', left: `${t.barcodeLeftMm}mm`, top: `${t.barcodeTopMm}mm` }}>
        <BarcodeMm code={cell.barcode} heightMm={t.barHeightMm} />
      </div>
      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          top: `${t.textTopMm}mm`,
          textAlign: 'center',
          whiteSpace: 'nowrap',
          fontFamily: '"Courier New", Courier, monospace',
          fontWeight: 700,
          fontSize: `${TEXT_HEIGHT_MM}mm`,
          lineHeight: 1,
          color: '#000',
        }}
      >
        {cell.sku}
      </div>
    </>
  );
}

/** Una fila del rollo, del ancho del papel y el alto de la etiqueta. */
function Row({ row, profile, guides }: { row: RollCell[]; profile: RollProfile; guides: boolean }) {
  const lefts = columnLeftsMm(profile);
  return (
    <div
      className="label-roll-row"
      style={{
        position: 'relative',
        width: `${profile.paperWidthMm}mm`,
        height: `${profile.labelHeightMm}mm`,
        overflow: 'hidden',
        background: guides ? '#e2e8f0' : '#fff',
      }}
    >
      {row.map((cell, c) => (
        <div key={c}>
          {guides && (
            // Dónde está la etiqueta según las medidas (sin el ajuste fino).
            <div
              style={{
                position: 'absolute',
                left: `${snapMm(lefts[c] - profile.offsetXMm)}mm`,
                top: 0,
                width: `${profile.labelWidthMm}mm`,
                height: `${profile.labelHeightMm}mm`,
                background: '#fff',
                borderRadius: '0.75mm',
                outline: '0.2mm dashed #94a3b8',
                outlineOffset: '-0.2mm',
              }}
            />
          )}
          <div
            style={{
              position: 'absolute',
              left: `${lefts[c]}mm`,
              top: `${snapMm(profile.offsetYMm)}mm`,
              width: `${profile.labelWidthMm}mm`,
              height: `${profile.labelHeightMm}mm`,
            }}
          >
            <Cell cell={cell} profile={profile} />
          </div>
        </div>
      ))}
    </div>
  );
}

/** Vista previa en pantalla: con el papel y las etiquetas dibujados, ampliada. */
export function LabelRollPreview({
  rows,
  profile,
  zoom = 2,
}: {
  rows: RollCell[][];
  profile: RollProfile;
  zoom?: number;
}) {
  return (
    <div style={{ zoom }} className="inline-block">
      {rows.map((row, i) => (
        <div key={i} style={{ marginBottom: `${Math.max(profile.gapYMm, 0.5)}mm` }}>
          <Row row={row} profile={profile} guides />
        </div>
      ))}
    </div>
  );
}

/**
 * Lo que va al papel. Va en un portal directo en <body> y, al imprimir, se oculta toda la
 * app (#root): el padding del layout y cualquier otro elemento correrían el contenido de
 * una página que mide exactamente 95 × 10 mm. Cada fila es una página; la última no fuerza
 * salto, para no sacar una fila en blanco al final.
 */
export function LabelRollPrint({ rows, profile }: { rows: RollCell[][]; profile: RollProfile }) {
  return createPortal(<LabelRollPages rows={rows} profile={profile} />, document.body);
}

/** El contenido impreso, aparte del portal para poder renderizarlo y probarlo solo. */
export function LabelRollPages({ rows, profile }: { rows: RollCell[][]; profile: RollProfile }) {
  const css = `
.label-roll-print { display: none; }
@media print {
  @page { size: ${profile.paperWidthMm}mm ${profile.labelHeightMm}mm; margin: 0; }
  html, body { margin: 0 !important; padding: 0 !important; background: #fff !important; }
  #root { display: none !important; }
  .label-roll-print { display: block; }
  .label-roll-print .label-roll-row { break-after: page; page-break-after: always; }
  .label-roll-print .label-roll-row:last-child { break-after: auto; page-break-after: auto; }
  .label-roll-print * { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
}`;
  return (
    <div className="label-roll-print">
      <style>{css}</style>
      {rows.map((row, i) => (
        <Row key={i} row={row} profile={profile} guides={false} />
      ))}
    </div>
  );
}
