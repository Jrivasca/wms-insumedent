import { fmtDate } from '../lib/format';

export interface PedidoInfoData {
  order_date?: string | null;
  quotation_number?: string | null;
  seller_code?: string | null;
  observations?: string | null;
}

/**
 * Cotización, vendedor y observaciones del pedido (y la fecha, si se pide).
 * El vendedor es el código de Defontana: el nombre vive en el módulo de Ventas, no contratado.
 * Las observaciones traen, en compras públicas, el código de Mercado Público de lo cotizado.
 */
export default function PedidoInfo({
  info,
  conFecha = false,
  completo = false,
  className = '',
}: {
  info?: PedidoInfoData | null;
  conFecha?: boolean;
  /** Observaciones completas (detalle del pedido); si no, en una línea recortada. */
  completo?: boolean;
  className?: string;
}) {
  if (!info) return null;
  const partes: React.ReactNode[] = [];
  if (conFecha && info.order_date) partes.push(<span key="f">Fecha {fmtDate(info.order_date)}</span>);
  partes.push(
    <span key="c">
      Cotización{' '}
      {info.quotation_number ? <span className="code">{info.quotation_number}</span> : '—'}
    </span>
  );
  partes.push(
    <span key="v">
      Vendedor {info.seller_code ? <span className="code">{info.seller_code}</span> : '—'}
    </span>
  );
  return (
    <div className={`text-xs text-slate-500 ${className}`}>
      <div className="flex flex-wrap gap-x-3 gap-y-0.5">{partes}</div>
      {info.observations && (
        <div
          className={completo ? 'mt-0.5 whitespace-pre-line' : 'mt-0.5 truncate'}
          title={info.observations}
        >
          Observaciones: {info.observations}
        </div>
      )}
    </div>
  );
}
