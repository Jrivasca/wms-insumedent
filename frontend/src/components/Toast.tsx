import { useEffect } from 'react';

export type ToastTone = 'info' | 'success' | 'warning' | 'error';

const TONE: Record<ToastTone, string> = {
  info: 'bg-blue-600',
  success: 'bg-emerald-600',
  warning: 'bg-amber-500',
  error: 'bg-red-600',
};

/**
 * Floating toast pinned near the bottom of the screen, above the content and the
 * bottom nav, so scan feedback (over-scan warnings, rejections, confirmations) is
 * always visible on mobile — no scrolling up to a banner. Auto-hides; tap to close.
 */
export default function Toast({
  message,
  tone = 'info',
  onClose,
  duration = 3200,
}: {
  message: string | null;
  tone?: ToastTone;
  onClose: () => void;
  duration?: number;
}) {
  useEffect(() => {
    if (!message) return;
    const t = setTimeout(onClose, duration);
    return () => clearTimeout(t);
  }, [message, duration, onClose]);

  if (!message) return null;
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-24 z-[60] flex justify-center px-4">
      <div
        onClick={onClose}
        role="alert"
        className={`pointer-events-auto max-w-md cursor-pointer rounded-xl px-4 py-3 text-center text-base font-semibold text-white shadow-2xl ${TONE[tone]}`}
      >
        {message}
      </div>
    </div>
  );
}
