import { useEffect, useRef } from 'react';
import { BrowserQRCodeSvgWriter } from '@zxing/library';

/** Renders a QR code (SVG) for the given value, reusing the already-installed @zxing/library. */
export default function QrCode({ value, size = 120 }: { value: string; size?: number }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.innerHTML = '';
    if (!value) return;
    try {
      const svg = new BrowserQRCodeSvgWriter().write(value, size, size);
      el.appendChild(svg);
    } catch {
      el.textContent = value; // fallback: show the raw URL if QR generation fails
    }
  }, [value, size]);

  return <div ref={ref} style={{ width: size, height: size }} aria-label={`QR ${value}`} />;
}
