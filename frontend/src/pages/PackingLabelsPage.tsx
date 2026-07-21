import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { getPackingTask } from '../api/packing';
import { getOrder } from '../api/orders';
import { errorMessage } from '../api/http';
import { ErrorBox, Loading } from '../components/Async';
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

  const nameBySku = useMemo(() => {
    const m: Record<string, string> = {};
    task?.lines.forEach((l) => {
      m[l.sku] = l.name;
    });
    return m;
  }, [task]);

  if (loading) return <Loading />;
  if (error) return <ErrorBox message={error} />;
  if (!task) return null;

  const packages = task.packages ?? [];
  const erpNumber = order?.erp_order_number ?? task.order_id;
  const customer = order?.customer ?? '—';

  return (
    <div className="mx-auto max-w-2xl">
      <div className="print:hidden mb-4 flex items-center justify-between">
        <button onClick={() => navigate(`/my/packing/${id}`)} className="text-sm text-slate-500 underline">
          ‹ Volver al packing
        </button>
        <button onClick={() => window.print()} className="btn-primary" disabled={packages.length === 0}>
          Imprimir etiquetas
        </button>
      </div>

      {packages.length === 0 ? (
        <div className="print:hidden text-sm text-slate-500">Esta tarea aún no tiene bultos.</div>
      ) : (
        <>
          <style>{`@media print { @page { margin: 10mm; } }`}</style>
          <div className="space-y-4">
            {packages.map((pkg, i) => {
              const agg: Record<string, number> = {};
              (pkg.items ?? []).forEach((it) => {
                if (it.sku) agg[it.sku] = (agg[it.sku] ?? 0) + (it.quantity ?? 0);
              });
              const rows = Object.entries(agg);
              const totalUnits = rows.reduce((a, [, q]) => a + q, 0);
              return (
                <div
                  key={pkg.package_id}
                  className="rounded-lg border-2 border-slate-800 p-4"
                  style={{ breakAfter: 'page' }}
                >
                  <div className="flex items-start justify-between border-b-2 border-slate-800 pb-2">
                    <div>
                      <div className="text-xs uppercase tracking-wide text-slate-500">Pedido</div>
                      <div className="text-xl font-bold">{erpNumber}</div>
                    </div>
                    <div className="text-right">
                      <div className="text-xs uppercase tracking-wide text-slate-500">Bulto</div>
                      <div className="text-4xl font-extrabold leading-none">
                        {i + 1}/{packages.length}
                      </div>
                    </div>
                  </div>

                  <div className="mt-2 text-lg font-semibold">Cliente: {customer}</div>
                  <div className="text-xs text-slate-500">{pkg.label ?? pkg.package_id}</div>

                  <table className="table mt-3 w-full">
                    <thead className="bg-slate-100">
                      <tr>
                        <th>Producto</th>
                        <th>SKU</th>
                        <th className="text-right">Cant.</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-200">
                      {rows.length === 0 ? (
                        <tr>
                          <td colSpan={3} className="text-sm text-slate-400">
                            Bulto vacío
                          </td>
                        </tr>
                      ) : (
                        rows.map(([sku, qty]) => (
                          <tr key={sku}>
                            <td>{nameBySku[sku] ?? sku}</td>
                            <td className="font-mono text-xs">{sku}</td>
                            <td className="text-right font-bold">{qty}</td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>

                  <div className="mt-2 text-right text-sm font-semibold">
                    Total: {totalUnits} unidades · {rows.length} ítems
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
