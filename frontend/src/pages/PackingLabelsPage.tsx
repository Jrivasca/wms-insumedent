import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, Printer } from 'lucide-react';
import { getPackingTask } from '../api/packing';
import { getOrder } from '../api/orders';
import { errorMessage } from '../api/http';
import { Empty, ErrorBox, Loading } from '../components/Async';
import QrCode from '../components/QrCode';
import type { Order, PackingTask } from '../types';

export default function PackingLabelsPage() {
  const { id = '' } = useParams();
  const navigate = useNavigate();
  const [task, setTask] = useState<PackingTask | null>(null);
  const [order, setOrder] = useState<Order | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const t = await getPackingTask(id);
        setTask(t);
        try {
          setOrder(await getOrder(t.order_id));
        } catch {
          // customer is best-effort
        }
      } catch (err) {
        setError(errorMessage(err));
      } finally {
        setLoading(false);
      }
    })();
  }, [id]);

  if (loading) return <Loading />;
  if (error) return <ErrorBox message={error} />;
  if (!task) return null;

  const packages = task.packages ?? [];
  const erpNumber = order?.erp_order_number ?? task.order_id;
  const customer = order?.customer ?? '—';

  return (
    <div className="mx-auto max-w-2xl">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2 print:hidden">
        <button onClick={() => navigate(`/my/packing/${id}`)} className="btn-ghost btn-sm -ml-2">
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          Volver al packing
        </button>
        <button
          onClick={() => window.print()}
          className="btn-primary"
          disabled={packages.length === 0}
        >
          <Printer className="h-4 w-4" aria-hidden="true" />
          Imprimir etiquetas
        </button>
      </div>

      {packages.length === 0 ? (
        <div className="print:hidden">
          <Empty
            label="Esta tarea aún no tiene bultos"
            hint="Crea al menos un bulto en la pantalla de packing para poder imprimir."
          />
        </div>
      ) : (
        <>
          {/* El marcado de la etiqueta está calibrado para papel: no se toca. */}
          <style>{`@media print { @page { margin: 10mm; } }`}</style>
          <div className="space-y-4">
            {packages.map((pkg, i) => (
              <div
                key={pkg.package_id}
                className="flex flex-col rounded-lg border-2 border-slate-800 p-6"
                style={{ breakAfter: 'page' }}
              >
                <div className="flex items-start justify-between border-b-2 border-slate-800 pb-2">
                  <div>
                    <div className="text-xs uppercase tracking-wide text-slate-500">Pedido</div>
                    <div className="text-2xl font-bold">{erpNumber}</div>
                  </div>
                  <div className="text-right">
                    <div className="text-xs uppercase tracking-wide text-slate-500">Bulto</div>
                    <div className="text-5xl font-extrabold leading-none">
                      {i + 1}/{packages.length}
                    </div>
                  </div>
                </div>

                <div className="mt-2 text-lg font-semibold">Cliente: {customer}</div>
                <div className="text-xs text-slate-500">{pkg.label ?? pkg.package_id}</div>

                {/* QR grande al centro: el detalle del bulto se ve al escanear (puede
                    tener muchos productos, por eso no se imprime el listado). */}
                {pkg.public_token ? (
                  <div className="mt-4 flex flex-col items-center justify-center">
                    <QrCode value={`${window.location.origin}/b/${pkg.public_token}`} size={260} />
                    <div className="mt-3 text-center text-base font-semibold">
                      Escanea para ver el detalle del bulto
                    </div>
                  </div>
                ) : (
                  <div className="mt-6 text-center text-sm text-slate-400">
                    Este bulto aún no tiene QR (se genera al despachar).
                  </div>
                )}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
