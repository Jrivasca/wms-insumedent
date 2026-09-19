/**
 * Marca la tarea que prepara el pendiente de un pedido ya despachado en parte: lo que se
 * pickee acá sale en otra guía (decisión A.7).
 */
export default function BackorderBadge({ sequence }: { sequence?: number }) {
  return (
    <span
      className="badge bg-amber-50 text-amber-800 ring-1 ring-inset ring-amber-200"
      title="Pendiente de un pedido ya despachado en parte: sale en otra guía"
    >
      Pendiente{sequence ? ` · ${sequence}ª guía` : ''}
    </span>
  );
}
