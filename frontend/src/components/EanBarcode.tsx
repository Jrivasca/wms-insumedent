// Dependency-free EAN-13 barcode renderer (SVG). The catalog barcodes are valid
// EAN-13 (12 digits + check digit), so this produces a real scannable symbol.

const L: Record<string, string> = {
  '0': '0001101', '1': '0011001', '2': '0010011', '3': '0111101', '4': '0100011',
  '5': '0110001', '6': '0101111', '7': '0111011', '8': '0110111', '9': '0001011',
};
const G: Record<string, string> = {
  '0': '0100111', '1': '0110011', '2': '0011011', '3': '0100001', '4': '0011101',
  '5': '0111001', '6': '0000101', '7': '0010001', '8': '0001001', '9': '0010111',
};
const R: Record<string, string> = {
  '0': '1110010', '1': '1100110', '2': '1101100', '3': '1000010', '4': '1011100',
  '5': '1001110', '6': '1010000', '7': '1000100', '8': '1001000', '9': '1110100',
};
// Parity pattern of the 6 left digits, selected by the first digit.
const PARITY: Record<string, string> = {
  '0': 'LLLLLL', '1': 'LLGLGG', '2': 'LLGGLG', '3': 'LLGGGL', '4': 'LGLLGG',
  '5': 'LGGLLG', '6': 'LGGGLL', '7': 'LGLGLG', '8': 'LGLGGL', '9': 'LGGLGL',
};

/** Return the 95-module bit string for a 13-digit EAN-13 code, or null if invalid. */
function ean13Bits(code: string): string | null {
  if (!/^\d{13}$/.test(code)) return null;
  const parity = PARITY[code[0]];
  const left = code.slice(1, 7);
  const right = code.slice(7, 13);
  let bits = '101'; // start guard
  for (let i = 0; i < 6; i++) {
    bits += parity[i] === 'L' ? L[left[i]] : G[left[i]];
  }
  bits += '01010'; // center guard
  for (let i = 0; i < 6; i++) {
    bits += R[right[i]];
  }
  bits += '101'; // end guard
  return bits;
}

interface Props {
  value: string;
  /** Bar height in px. */
  height?: number;
  /** Width of one module (narrowest bar) in px. */
  module?: number;
  showText?: boolean;
}

export default function EanBarcode({ value, height = 44, module = 1.5, showText = false }: Props) {
  const bits = ean13Bits(value);
  if (!bits) {
    // Not an EAN-13 (e.g. a non-numeric/internal code): show the raw value.
    return <div className="font-mono text-xs">{value || '—'}</div>;
  }
  const width = bits.length * module;
  const bars = [];
  for (let i = 0; i < bits.length; i++) {
    if (bits[i] === '1') {
      bars.push(<rect key={i} x={i * module} y={0} width={module} height={height} fill="#000" />);
    }
  }
  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      shapeRendering="crispEdges"
      role="img"
      aria-label={`Código de barras ${value}`}
    >
      {bars}
      {showText && (
        <text x={width / 2} y={height} textAnchor="middle" fontSize={module * 6} fontFamily="monospace">
          {value}
        </text>
      )}
    </svg>
  );
}
