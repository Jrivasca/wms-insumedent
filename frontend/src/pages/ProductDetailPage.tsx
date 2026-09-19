import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, Boxes, PackageCheck } from 'lucide-react';
import { getProduct } from '../api/products';
import { listBalances, listMovements } from '../api/inventory';
import { errorMessage } from '../api/http';
import { Empty, ErrorBox, Loading, PageHeader } from '../components/Async';
import DataTable, { MobileCardList, type Column } from '../components/DataTable';
import MetricCard from '../components/MetricCard';
import StatusBadge from '../components/StatusBadge';
import { movementLabel } from '../lib/inventory';
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

  const balanceColumns: Column<InventoryBalance>[] = [
    {
      key: 'location',
      header: 'Ubicación',
      render: (b) => <span className="code-strong">{b.location_code ?? b.location_id}</span>,
    },
    {
      key: 'lot',
      header: 'Lote / Serie',
      render: (b) => (
        <span className="code">
          {[b.lot_number, b.serial_number].filter(Boolean).join(' / ') || '—'}
        </span>
      ),
    },
    { key: 'on_hand', header: 'En mano', align: 'right', render: (b) => b.quantity_on_hand },
    {
      key: 'reserved',
      header: 'Reservado',
      align: 'right',
      secondary: true,
      render: (b) => b.quantity_reserved,
    },
    {
      key: 'available',
      header: 'Disponible',
      align: 'right',
      render: (b) => <span className="font-semibold text-slate-900">{b.quantity_available}</span>,
    },
    {
      key: 'blocked',
      header: 'Bloqueado',
      align: 'right',
      secondary: true,
      render: (b) =>
        b.quantity_blocked > 0 ? (
          <span className="font-semibold text-amber-900">{b.quantity_blocked}</span>
        ) : (
          0
        ),
    },
  ];

  const movementColumns: Column<InventoryMovement>[] = [
    {
      key: 'date',
      header: 'Fecha',
      render: (m) => (
        <span className="whitespace-nowrap text-xs text-slate-500">
          {new Date(m.created_at).toLocaleString('es-CL')}
        </span>
      ),
    },
    {
      key: 'type',
      header: 'Tipo',
      render: (m) => <span className="text-slate-700">{movementLabel(m.movement_type)}</span>,
    },
    {
      key: 'route',
      header: 'Origen → Destino',
      secondary: true,
      render: (m) => (
        <span className="code">
          {m.from_location_id ?? '—'} → {m.to_location_id ?? '—'}
        </span>
      ),
    },
    { key: 'qty', header: 'Cantidad', align: 'right', render: (m) => m.quantity },
    {
      key: 'reason',
      header: 'Motivo',
      secondary: true,
      render: (m) => <span className="text-xs text-slate-500">{m.reason ?? '—'}</span>,
    },
  ];

  return (
    <div>
      <button
        onClick={() => navigate('/products')}
        className="btn-ghost btn-sm mb-2 -ml-2 inline-flex"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden="true" />
        Volver a productos
      </button>

      <PageHeader
        title={product.name}
        subtitle={`SKU ${product.sku}`}
        actions={<StatusBadge status={product.is_active === false ? 'inactive' : 'active'} />}
      />

      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <MetricCard
          label="Stock en mano"
          value={totalOnHand}
          hint="Suma de todas las ubicaciones"
          icon={Boxes}
        />
        <MetricCard
          label="Disponible"
          value={totalAvailable}
          hint="Descontado lo reservado"
          tone={totalAvailable > 0 ? 'ok' : 'warn'}
          icon={PackageCheck}
        />
        <div className="card">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Unidad</p>
          <p className="mt-1 text-lg font-semibold text-slate-900">{product.unit ?? '—'}</p>
          <p className="mt-0.5 text-xs text-slate-500">{product.category ?? 'Sin categoría'}</p>
        </div>
        <div className="card">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Marca</p>
          <p className="mt-1 text-lg font-semibold text-slate-900">{product.brand ?? '—'}</p>
          <p className="mt-0.5 text-xs text-slate-500">
            {product.cost != null ? `Costo $${product.cost}` : 'Sin costo'}
            {product.sale_price != null ? ` · Venta $${product.sale_price}` : ''}
          </p>
        </div>
      </div>

      <div className="card mb-6">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
          Códigos de barra
        </p>
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
          <p className="text-sm text-slate-500">
            Sin códigos de barra: este producto no se puede escanear en picking ni en packing.
          </p>
        )}
      </div>

      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
        Saldos por ubicación
      </h2>
      {balances.length === 0 ? (
        <Empty label="Sin stock" hint="Este producto no tiene saldo en ninguna ubicación." />
      ) : (
        <>
          <div className="hidden lg:block">
            <DataTable columns={balanceColumns} rows={balances} keyOf={(b) => b.id} />
          </div>
          <div className="lg:hidden">
            <MobileCardList
              rows={balances}
              keyOf={(b) => b.id}
              render={(b) => (
                <div>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="code-strong">{b.location_code ?? b.location_id}</span>
                    <span className="text-sm">
                      <span className="font-bold tabular-nums text-slate-900">
                        {b.quantity_available}
                      </span>
                      <span className="text-slate-500"> disponibles</span>
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-slate-500">
                    En mano {b.quantity_on_hand} · Reservado {b.quantity_reserved}
                    {b.quantity_blocked > 0 && (
                      <span className="font-medium text-amber-900">
                        {' '}
                        · Bloqueado {b.quantity_blocked}
                      </span>
                    )}
                    {[b.lot_number, b.serial_number].filter(Boolean).length > 0 && (
                      <> · {[b.lot_number, b.serial_number].filter(Boolean).join(' / ')}</>
                    )}
                  </p>
                </div>
              )}
            />
          </div>
        </>
      )}

      <h2 className="mb-2 mt-6 text-sm font-semibold uppercase tracking-wide text-slate-500">
        Movimientos recientes
      </h2>
      {movements.length === 0 ? (
        <Empty label="Sin movimientos" hint="Aquí aparece cada entrada, salida y traslado." />
      ) : (
        <>
          <div className="hidden lg:block">
            <DataTable columns={movementColumns} rows={movements} keyOf={(m) => m.id} />
          </div>
          <div className="lg:hidden">
            <MobileCardList
              rows={movements}
              keyOf={(m) => m.id}
              render={(m) => (
                <div>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-sm font-medium text-slate-900">
                      {movementLabel(m.movement_type)}
                    </span>
                    <span className="text-sm font-bold tabular-nums text-slate-900">
                      {m.quantity}
                    </span>
                  </div>
                  <p className="mt-0.5 text-xs text-slate-500">
                    {new Date(m.created_at).toLocaleString('es-CL')}
                  </p>
                  {m.reason && <p className="mt-1 text-xs text-slate-500">{m.reason}</p>}
                </div>
              )}
            />
          </div>
        </>
      )}
    </div>
  );
}
