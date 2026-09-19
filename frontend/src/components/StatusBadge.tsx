import { statusClasses, statusLabel, statusTone, TONE_DOTS } from '../lib/status';

/**
 * Estado en español con color con significado. El valor interno no se muestra al usuario
 * (queda en `title` para soporte).
 */
export default function StatusBadge({
  status,
  withDot = false,
}: {
  status?: string | null;
  withDot?: boolean;
}) {
  const label = statusLabel(status);
  return (
    <span className={`badge ${statusClasses(status)}`} title={status ?? undefined}>
      {withDot && <span className={`h-1.5 w-1.5 rounded-full ${TONE_DOTS[statusTone(status)]}`} />}
      {label}
    </span>
  );
}
