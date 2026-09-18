import { useEffect, useState } from 'react';
import { CheckCheck } from 'lucide-react';
import { createTransfer } from '../api/inventory';
import { listWarehouses } from '../api/warehouses';
import { errorMessage } from '../api/http';
import { ErrorBox, PageHeader } from '../components/Async';
import { Field, ProductPicker, SelectField } from '../components/Form';
import LocationCombobox from '../components/LocationCombobox';
import type { Product, Warehouse } from '../types';

export default function InventoryTransferPage() {
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [product, setProduct] = useState<Product | null>(null);
  const [warehouseId, setWarehouseId] = useState('');
  const [fromLocation, setFromLocation] = useState('');
  const [toLocation, setToLocation] = useState('');
  const [quantity, setQuantity] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    listWarehouses().then(setWarehouses).catch(() => undefined);
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!product) {
      setError('Elige el producto que vas a mover.');
      return;
    }
    if (!fromLocation || !toLocation) {
      setError('Elige la ubicación de origen y la de destino.');
      return;
    }
    if (fromLocation === toLocation) {
      setError('El origen y el destino son la misma ubicación.');
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await createTransfer({
        product_id: product.id,
        warehouse_id: warehouseId,
        from_location_id: fromLocation,
        to_location_id: toLocation,
        quantity: Number(quantity),
      });
      setNotice(`Transferencia realizada: ${quantity} unidades de ${product.sku}`);
      setQuantity('');
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-xl">
      <PageHeader
        title="Transferencia de inventario"
        subtitle="Mueve stock entre ubicaciones de la misma bodega"
      />

      {notice && (
        <div className="mb-3 flex items-start gap-2 rounded-card border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
          <CheckCheck className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          {notice}
        </div>
      )}
      {error && <ErrorBox message={error} />}

      <form onSubmit={submit} className="card space-y-3">
        <ProductPicker value={product} onChange={setProduct} />
        <SelectField
          label="Bodega"
          value={warehouseId}
          onChange={(v) => {
            setWarehouseId(v);
            setFromLocation('');
            setToLocation('');
          }}
          options={warehouses.map((w) => ({ value: w.id, label: w.name }))}
          required
        />
        <LocationCombobox
          label="Ubicación origen"
          value={fromLocation}
          onChange={setFromLocation}
          warehouseId={warehouseId}
          requireWarehouse
        />
        <LocationCombobox
          label="Ubicación destino"
          value={toLocation}
          onChange={setToLocation}
          warehouseId={warehouseId}
          requireWarehouse
          disabledIds={fromLocation ? [fromLocation] : undefined}
          hint="No puede ser la misma ubicación de origen."
        />
        <Field label="Cantidad" type="number" value={quantity} onChange={setQuantity} required />
        <button type="submit" className="btn-primary btn-xl w-full" disabled={busy}>
          {busy ? 'Transfiriendo…' : 'Transferir'}
        </button>
      </form>
    </div>
  );
}
