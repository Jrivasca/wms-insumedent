import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import type { AxiosError } from 'axios';
import { AlertTriangle, Loader2, PackageX, Truck } from 'lucide-react';
import { getPublicBulto } from '../api/publicBulto';
import type { PublicBultoView } from '../types';

type Status = 'loading' | 'ok' | 'notfound' | 'expired' | 'error';

function fmtDate(iso?: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString('es-CL');
}

/** Página pública: la ve el cliente al escanear el QR de la etiqueta del bulto. */
export default function PublicBultoPage() {
  const { token = '' } = useParams();
  const [view, setView] = useState<PublicBultoView | null>(null);
  const [status, setStatus] = useState<Status>('loading');

  useEffect(() => {
    let alive = true;
    (async () => {
      setStatus('loading');
      try {
        const v = await getPublicBulto(token);
        if (!alive) return;
        setView(v);
        setStatus('ok');
      } catch (err) {
        if (!alive) return;
        const code = (err as AxiosError)?.response?.status;
        setStatus(code === 404 ? 'notfound' : code === 410 ? 'expired' : 'error');
      }
    })();
    return () => {
      alive = false;
    };
  }, [token]);

  return (
    <div className="min-h-screen bg-slate-100 px-4 py-6">
      <div className="mx-auto max-w-md">
        <div className="mb-3 flex flex-col items-center">
          <span className="mb-2 flex h-9 w-9 items-center justify-center rounded-md bg-brand text-sm font-bold text-white">
            S
          </span>
          <span className="text-lg font-extrabold tracking-tight text-slate-800">INSUMEDENT</span>
          <span className="text-xs uppercase tracking-wide text-slate-500">
            Detalle del bulto
          </span>
        </div>

        <div className="rounded-card bg-white p-5 shadow-card">
          {status === 'loading' && (
            <p
              className="flex items-center justify-center gap-2 py-10 text-sm text-slate-500"
              role="status"
            >
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              Cargando…
            </p>
          )}

          {status === 'notfound' && (
            <div className="py-10 text-center">
              <PackageX className="mx-auto h-8 w-8 text-slate-400" aria-hidden="true" />
              <p className="mt-2 font-semibold text-slate-800">Bulto no encontrado</p>
              <p className="text-sm text-slate-500">Este código QR no es válido.</p>
            </div>
          )}

          {status === 'expired' && (
            <div className="py-10 text-center">
              <AlertTriangle className="mx-auto h-8 w-8 text-amber-600" aria-hidden="true" />
              <p className="mt-2 font-semibold text-slate-800">Este enlace ya caducó</p>
              <p className="text-sm text-slate-500">Solicita una etiqueta actualizada.</p>
            </div>
          )}

          {status === 'error' && (
            <div className="py-10 text-center">
              <AlertTriangle className="mx-auto h-8 w-8 text-red-600" aria-hidden="true" />
              <p className="mt-2 font-semibold text-slate-800">No se pudo cargar el detalle</p>
              <p className="text-sm text-slate-500">
                Puede ser un problema de conexión. Inténtalo de nuevo en unos minutos.
              </p>
              <button onClick={() => window.location.reload()} className="btn-secondary mt-3">
                Reintentar
              </button>
            </div>
          )}

          {status === 'ok' && view && (
            <>
              <div className="flex items-start justify-between border-b border-slate-200 pb-3">
                <div>
                  <div className="text-xs uppercase tracking-wide text-slate-500">Pedido</div>
                  <div className="text-lg font-bold text-slate-900">{view.order_number ?? '—'}</div>
                </div>
                <div className="text-right">
                  <div className="text-xs uppercase tracking-wide text-slate-500">Bulto</div>
                  <div className="text-2xl font-extrabold leading-none tabular-nums text-slate-900">
                    {view.package_number}/{view.package_count}
                  </div>
                </div>
              </div>

              {view.customer && (
                <div className="mt-3 text-sm">
                  <span className="text-slate-500">Cliente: </span>
                  <span className="font-medium text-slate-800">{view.customer}</span>
                </div>
              )}

              <table className="mt-3 w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-200 text-left text-xs uppercase text-slate-500">
                    <th className="py-1">Producto</th>
                    <th className="py-1">SKU</th>
                    <th className="py-1 text-right">Cant.</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {view.items.length === 0 ? (
                    <tr>
                      <td colSpan={3} className="py-3 text-center text-slate-500">
                        Bulto sin ítems
                      </td>
                    </tr>
                  ) : (
                    view.items.map((it) => (
                      <tr key={it.sku}>
                        <td className="py-1.5 pr-2 text-slate-700">{it.name ?? it.sku}</td>
                        <td className="py-1.5 pr-2">
                          <span className="code">{it.sku}</span>
                        </td>
                        <td className="py-1.5 text-right font-bold tabular-nums text-slate-900">
                          {it.quantity}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>

              <div className="mt-2 text-right text-sm font-semibold text-slate-700">
                Total: {view.total_units} unidades · {view.item_count} ítems
              </div>

              <div className="mt-4 space-y-1 border-t border-slate-200 pt-3 text-xs text-slate-500">
                {view.packed_at && <div>Empacado: {fmtDate(view.packed_at)}</div>}
                {view.dispatch?.dispatched ? (
                  <div className="flex items-start gap-1.5">
                    <Truck className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                    <span>
                      Despachado
                      {view.dispatch.dispatch_date
                        ? ` el ${fmtDate(view.dispatch.dispatch_date)}`
                        : ''}
                      {view.dispatch.carrier ? ` · ${view.dispatch.carrier}` : ''}
                      {view.dispatch.tracking_number
                        ? ` · Seguimiento ${view.dispatch.tracking_number}`
                        : ''}
                    </span>
                  </div>
                ) : (
                  <div>Estado: preparado para despacho</div>
                )}
              </div>
            </>
          )}
        </div>

        <p className="mt-3 text-center text-[11px] text-slate-500">
          Consulta segura · INSUMEDENT WMS
        </p>
      </div>
    </div>
  );
}
