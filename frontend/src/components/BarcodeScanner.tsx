import { useCallback, useEffect, useRef, useState } from 'react';
import { BrowserMultiFormatReader, IScannerControls } from '@zxing/browser';
import { BarcodeFormat, DecodeHintType } from '@zxing/library';

export type ScanFeedback = 'idle' | 'success' | 'error' | 'warning';

// Decode hints: try harder and restrict to the formats we actually use. This makes
// real-world reads (angled/low-contrast CODE128 & EAN-13 labels) far more reliable.
const SCAN_HINTS = new Map<DecodeHintType, unknown>();
SCAN_HINTS.set(DecodeHintType.TRY_HARDER, true);
SCAN_HINTS.set(DecodeHintType.POSSIBLE_FORMATS, [
  BarcodeFormat.EAN_13,
  BarcodeFormat.EAN_8,
  BarcodeFormat.UPC_A,
  BarcodeFormat.CODE_128,
  BarcodeFormat.CODE_39,
  BarcodeFormat.ITF,
  BarcodeFormat.QR_CODE,
]);

interface Props {
  onScan: (code: string) => void;
  feedback?: ScanFeedback;
  /** Optional label/hint shown above the input. */
  hint?: string;
  /** Keep the HID input auto-focused (default true). Disable when a modal owns focus. */
  autoFocus?: boolean;
}

const FEEDBACK_BORDER: Record<ScanFeedback, string> = {
  idle: 'border-slate-300',
  success: 'border-emerald-500 ring-2 ring-emerald-400',
  error: 'border-red-500 ring-2 ring-red-400',
  warning: 'border-amber-500 ring-2 ring-amber-400',
};

const FEEDBACK_BANNER: Record<ScanFeedback, string> = {
  idle: '',
  success: 'bg-emerald-500 text-white',
  error: 'bg-red-500 text-white',
  warning: 'bg-amber-500 text-white',
};

/** Short WebAudio beep. */
function beep(success = true) {
  try {
    const Ctx =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    const ctx = new Ctx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.type = 'square';
    osc.frequency.value = success ? 880 : 220;
    gain.gain.value = 0.1;
    osc.start();
    setTimeout(() => {
      osc.stop();
      ctx.close().catch(() => undefined);
    }, 120);
  } catch {
    // audio not available
  }
}

export default function BarcodeScanner({
  onScan,
  feedback = 'idle',
  hint,
  autoFocus = true,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const controlsRef = useRef<IScannerControls | null>(null);
  const readerRef = useRef<BrowserMultiFormatReader | null>(null);
  const lastScanRef = useRef<{ code: string; at: number }>({ code: '', at: 0 });
  const [cameraOn, setCameraOn] = useState(false);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [value, setValue] = useState('');

  // Phones/tablets (coarse primary pointer): the field must be tap-to-type so the
  // on-screen keyboard opens. Desktops keep the hardware-scanner auto-focus.
  const isTouchDevice =
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(pointer: coarse)').matches;

  const fire = useCallback(
    (code: string, isError = false) => {
      const trimmed = code.trim();
      if (!trimmed) return;
      // debounce duplicate reads within 1.2s (camera fires repeatedly)
      const now = Date.now();
      if (lastScanRef.current.code === trimmed && now - lastScanRef.current.at < 1200) {
        return;
      }
      lastScanRef.current = { code: trimmed, at: now };
      beep(!isError);
      navigator.vibrate?.(50);
      onScan(trimmed);
    },
    [onScan]
  );

  // Keep HID input focused (desktop only). On touch devices never steal focus:
  // iOS won't open the keyboard from a programmatic focus, and re-focusing
  // blocks the tap-to-type gesture.
  const refocus = useCallback(() => {
    if (autoFocus && !cameraOn && !isTouchDevice) {
      // small timeout so it survives blur events
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [autoFocus, cameraOn, isTouchDevice]);

  useEffect(() => {
    refocus();
  }, [refocus]);

  // Camera lifecycle.
  useEffect(() => {
    let cancelled = false;
    async function start() {
      setCameraError(null);
      try {
        const reader = new BrowserMultiFormatReader(SCAN_HINTS);
        readerRef.current = reader;
        // Force the back (environment) camera and request a higher resolution so small
        // or angled barcodes are legible. facingMode fixes the usual "no escanea" (the
        // default device is often the front camera, which can't focus on a barcode).
        const controls = await reader.decodeFromConstraints(
          {
            video: {
              facingMode: { ideal: 'environment' },
              width: { ideal: 1280 },
              height: { ideal: 720 },
            },
          },
          videoRef.current ?? undefined,
          (result) => {
            if (result) {
              fire(result.getText());
              // Apagar la cámara tras leer un código: evita el re-escaneo en ráfaga.
              // El operario vuelve a tocar "Cámara" para el siguiente producto.
              setCameraOn(false);
            }
          }
        );
        if (cancelled) {
          controls.stop();
        } else {
          controlsRef.current = controls;
        }
      } catch (err) {
        setCameraError(
          'No se pudo acceder a la cámara. Verifique permisos o use el escáner físico.'
        );
        setCameraOn(false);
        // eslint-disable-next-line no-console
        console.error(err);
      }
    }

    if (cameraOn) {
      start();
    }

    return () => {
      cancelled = true;
      controlsRef.current?.stop();
      controlsRef.current = null;
      readerRef.current = null;
    };
  }, [cameraOn, fire]);

  // Cleanup on unmount.
  useEffect(() => {
    return () => {
      controlsRef.current?.stop();
    };
  }, []);

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') {
      e.preventDefault();
      fire(value);
      setValue('');
    }
  }

  return (
    <div className="space-y-2">
      {feedback !== 'idle' && (
        <div className={`rounded-md px-3 py-2 text-center text-sm font-semibold ${FEEDBACK_BANNER[feedback]}`}>
          {feedback === 'success' && 'Código correcto'}
          {feedback === 'error' && 'Código incorrecto'}
          {feedback === 'warning' && 'Atención'}
        </div>
      )}

      {hint && <p className="text-sm text-slate-500">{hint}</p>}

      <div className="flex gap-2">
        <input
          ref={inputRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          onBlur={refocus}
          autoFocus={autoFocus && !isTouchDevice}
          inputMode="text"
          enterKeyHint="done"
          placeholder={isTouchDevice ? 'Toque aquí para escribir el código' : 'Escanee o ingrese código…'}
          className={`flex-1 rounded-md border bg-white px-3 py-3 text-base outline-none ${FEEDBACK_BORDER[feedback]}`}
          aria-label="Entrada de código de barras"
        />
        <button
          type="button"
          onClick={() => setCameraOn((v) => !v)}
          className={`btn ${cameraOn ? 'btn-danger' : 'btn-secondary'} whitespace-nowrap`}
        >
          {cameraOn ? 'Apagar cámara' : '📷 Cámara'}
        </button>
      </div>

      {isTouchDevice && !cameraOn && (
        <p className="text-xs text-slate-400">
          Toque el campo para escribir con el teclado, o use la cámara para escanear.
        </p>
      )}

      {cameraError && <p className="text-sm text-red-600">{cameraError}</p>}

      {cameraOn && (
        <div className="overflow-hidden rounded-md border border-slate-300 bg-black">
          <video ref={videoRef} className="h-56 w-full object-cover" muted playsInline />
        </div>
      )}
    </div>
  );
}
