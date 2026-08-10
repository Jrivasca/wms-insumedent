import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { getProduct } from '../api/products';
import { listBalances, listMovements } from '../api/inventory';
import { errorMessage } from '../api/http';
import { ErrorBox, Loading, PageHeader } from '../components/Async';
import type { InventoryBalance, InventoryMovement, Product } from '../types';

export default function ProductDetailPage() {
  const { id = '' } = useParams();
  const navigate = useNavigate();
  const [product, setProduct] = useState<Product | null>(null);
  const [balances, setBalances] = useState<InventoryBalance[]>([]);
  const [movements, setMovements] = useState<InventoryMovement[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const p = await getProduct(id);
        setProduct(p);
        const [bal, mov] = await Promise.all([
          listBalances({ product_id: id, limit: 200 }).catch(() => null),
          listMovements({ product_id: id, limit: 50 }).catch(() => null),
        ]);
        setBalances(bal?.items ?? []);
        setMovements(mov?.items ?? []);
      } catch (err) {
        setError(errorMessage(err));
      } finally {
        setLoading(false);
      }
    })();
  }, [id]);

  if (loading) return <Loading />;
  if (error) return <ErrorBox message={error} />;
  if (!product) return null;

  const totalOnHand = balances.reduce((a, b) => a + (b.quantity_on_hand ?? 0), 0);
  const totalAvailable = balances.reduce((a, b) => a + (b.quantity_available ?? 0), 0);

  return (
    <div>
      <button onClick={() => navigate('/products')} className="mb-3 text-sm text-slate-500 underline">
        ‹ Volver a productos
      </button>
      <PageHeader title={product.name} subtitle={`SKU ${product.sku}`} />

      {/* Datos del producto */}
      <div className="card mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Field label="Categoría" value={product.category ?? '—'} />
        <Field label="Unidad" value={product.unit ?? '—'} />
        <Field label="Marca" value={product.brand ?? '—'} />
        <Field
          label="Estado"
          value={product.is_active === false ? 'Inactivo' : 'Activo'}
        />
        <Field label="Costo" value={product.cost != null ? `$${product.cost}` : '—'} />
        <Field label="Precio venta" value={product.sale_price != null ? `$${product.sale_price}` : '—'} />
        <Field label="Stock total (en mano)" value={String(totalOnHand)} />
        <Field label="Disponible total" value={String(totalAvailable)} />
      </div>

      {/* Códigos de barra */}
      <div className="card mb-4">
        <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
          Códigos de barra
        </div>
        {product.barcodes?.length ? (
          <div className="flex flex-wrap gap-1">
            {product.barcodes.map((b, i) => (
              <span key={i} className="badge bg-slate-100 font-mono text-slate-700">
                {b.barcode}
                {b.type ? ` (${b.type})` : ''}
              </span>
            ))}
          </div>
        ) : (
          <span className="text-sm text-slate-400">Sin códigos de barra</span>
        )}
      </div>

      {/* Saldos por ubicación */}
      <h2 className="mb-2 text-lg font-semibold">Saldos por ubicación</h2>
      {balances.length === 0 ? (
        <div className="card mb-4 text-sm text-slate-400">Sin stock en ninguna ubicación.</div>
      ) : (
        <div className="mb-4 overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="table w-full">
            <thead className="bg-slate-50">
              <tr>
                <th>Ubicación</th>
                <th>Lote/Serie</th>
                <th className="text-right">En mano</th>
                <th className="text-right">Reservado</th>
                <th className="text-right">Disponible</th>
                <th className="text-right">Bloqueado</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {balances.map((b) => (
                <tr key={b.id}>
                  <td className="font-mono text-xs">{b.location_code ?? b.location_id}</td>
                  <td className="text-xs text-slate-500">
                    {[b.lot_number, b.serial_number].filter(Boolean).join(' / ') || '—'}
                  </td>
                  <td className="text-right">{b.quantity_on_hand}</td>
                  <td className="text-right">{b.quantity_reserved}</td>
                  <td className="text-right font-semibold">{b.quantity_available}</td>
                  <td className="text-right">{b.quantity_blocked}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Movimientos */}
      <h2 className="mb-2 text-lg font-semibold">Movimientos recientes</h2>
      {movements.length === 0 ? (
        <div className="card text-sm text-slate-400">Sin movimientos registrados.</div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="table w-full">
            <thead className="bg-slate-50">
              <tr>
                <th>Fecha</th>
                <th>Tipo</th>
                <th>Origen</th>
                <th>Destino</th>
                <th className="text-right">Cantidad</th>
                <th>Motivo</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {movements.map((m) => (
                <tr key={m.id}>
                  <td className="text-xs text-slate-500">{new Date(m.created_at).toLocaleString()}</td>
                  <td>{m.movement_type}</td>
                  <td className="text-xs">{m.from_location_id ?? '—'}</td>
                  <td className="text-xs">{m.to_location_id ?? '—'}</td>
                  <td className="text-right">{m.quantity}</td>
                  <td className="text-xs text-slate-500">{m.reason ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-slate-500">{label}</div>
      <div className="font-medium">{value}</div>
    </div>
  );
}
