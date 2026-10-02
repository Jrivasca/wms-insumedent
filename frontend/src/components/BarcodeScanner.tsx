import { useCallback, useEffect, useRef, useState } from 'react';
import { BrowserMultiFormatReader } from '@zxing/browser';
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

// Lector nativo del navegador (Chrome en Android, con el motor del sistema): decodifica en
// código nativo, mucho más rápido que ZXing en JavaScript. En un Android de gama básica ZXing
// tardaba varios segundos por lectura; Safari (iPhone) no lo trae y sigue con ZXing.
const NATIVE_FORMATS = ['ean_13', 'ean_8', 'upc_a', 'code_128', 'code_39', 'itf', 'qr_code'];

interface NativeDetector {
  detect: (source: HTMLVideoElement) => Promise<{ rawValue: string }[]>;
}

async function nativeDetector(): Promise<NativeDetector | null> {
  const BD = (window as unknown as { BarcodeDetector?: any }).BarcodeDetector; // eslint-disable-line @typescript-eslint/no-explicit-any
  if (!BD) return null;
  try {
    const supported: string[] = await BD.getSupportedFormats();
    const formats = NATIVE_FORMATS.filter((f) => supported.includes(f));
    // Sin EAN-13 no sirve para el catálogo: mejor ZXing.
    if (!formats.includes('ean_13')) return null;
    return new BD({ formats }) as NativeDetector;
  } catch {
    return null;
  }
}

const VIDEO_CONSTRAINTS: MediaTrackConstraints = {
  facingMode: { ideal: 'environment' },
  width: { ideal: 1280 },
  height: { ideal: 720 },
};

/** Enfoque continuo donde el teléfono lo permite: sin esto muchas cámaras quedan fijas. */
async function tryContinuousFocus(stream: MediaStream) {
  const track = stream.getVideoTracks()[0];
  const caps = (track?.getCapabilities?.() ?? {}) as { focusMode?: string[] };
  if (caps.focusMode?.includes('continuous')) {
    try {
      await track.applyConstraints({ advanced: [{ focusMode: 'continuous' } as MediaTrackConstraintSet] });
    } catch {
      // No todas las cámaras aceptan el cambio: se sigue con el enfoque por defecto.
    }
  }
}

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
  const controlsRef = useRef<{ stop: () => void } | null>(null);
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
    if (!autoFocus || cameraOn || isTouchDevice) return;
    // small timeout so it survives blur events; el foco ya se movió al evaluar activeElement.
    setTimeout(() => {
      const active = document.activeElement as HTMLElement | null;
      // No robar el foco si el usuario está escribiendo en otro campo (ej. la etiqueta del bulto),
      // en un textarea/select, en un elemento editable o dentro de un modal/diálogo.
      if (
        active &&
        active !== inputRef.current &&
        (active.tagName === 'INPUT' ||
          active.tagName === 'TEXTAREA' ||
          active.tagName === 'SELECT' ||
          active.isContentEditable ||
          active.closest('[role="dialog"],[aria-modal="true"]'))
      ) {
        return;
      }
      inputRef.current?.focus();
    }, 0);
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
        const detector = await nativeDetector();
        if (detector) {
          const stream = await navigator.mediaDevices.getUserMedia({ video: VIDEO_CONSTRAINTS });
          const video = videoRef.current;
          if (cancelled || !video) {
            stream.getTracks().forEach((t) => t.stop());
            return;
          }
          video.srcObject = stream;
          await video.play();
          await tryContinuousFocus(stream);
          // Un intento a la vez: en un teléfono lento los detect() se apilarían.
          let ocupado = false;
          const timer = window.setInterval(async () => {
            if (ocupado || video.readyState < 2) return;
            ocupado = true;
            try {
              const codes = await detector.detect(video);
              if (codes.length > 0 && codes[0].rawValue) {
                fire(codes[0].rawValue);
                // Apagar la cámara tras leer: evita el re-escaneo en ráfaga.
                setCameraOn(false);
              }
            } catch {
              // Un cuadro que falla no detiene la lectura.
            } finally {
              ocupado = false;
            }
          }, 120);
          controlsRef.current = {
            stop: () => {
              window.clearInterval(timer);
              stream.getTracks().forEach((t) => t.stop());
            },
          };
          return;
        }

        // Respaldo: ZXing. 100 ms entre intentos (por defecto espera 500 ms entre cuadros).
        const reader = new BrowserMultiFormatReader(SCAN_HINTS, { delayBetweenScanAttempts: 100 });
        // Force the back (environment) camera and request a higher resolution so small
        // or angled barcodes are legible. facingMode fixes the usual "no escanea" (the
        // default device is often the front camera, which can't focus on a barcode).
        const controls = await reader.decodeFromConstraints(
          { video: VIDEO_CONSTRAINTS },
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
          const stream = videoRef.current?.srcObject;
          if (stream instanceof MediaStream) await tryContinuousFocus(stream);
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

  // El feedback del escaneo se muestra sin alterar el layout: color del borde del input
  // (``FEEDBACK_BORDER``) + el Toast overlay de la página. Antes había un banner inline que
  // aparecía/desaparecía y empujaba los botones de abajo, provocando clics accidentales.
  return (
    <div className="space-y-2">
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
          // ``min-w-0``: un <input> trae un ancho intrínseco propio y ``flex-1`` no lo deja
          // encogerse por debajo de él, así que a 390 px el botón «Cámara» se salía del
          // contenedor y la página ganaba scroll horizontal.
          className={`min-w-0 flex-1 rounded-md border bg-white px-3 py-3 text-base outline-none ${FEEDBACK_BORDER[feedback]}`}
          aria-label="Entrada de código de barras"
        />
        <button
          type="button"
          onClick={() => setCameraOn((v) => !v)}
          className={`btn shrink-0 ${cameraOn ? 'btn-danger' : 'btn-secondary'} whitespace-nowrap`}
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
          <p className="bg-black/80 px-3 py-1 text-center text-xs text-slate-200">
            Acerque el código a unos 10–15 cm, derecho y con buena luz.
          </p>
        </div>
      )}
    </div>
  );
}
