import { useEffect, useState } from 'react';
import { createTransfer } from '../api/inventory';
import { listWarehouses, listLocations } from '../api/warehouses';
import { errorMessage } from '../api/http';
import { ErrorBox, PageHeader } from '../components/Async';
import { Field, ProductPicker, SelectField } from '../components/Form';
import type { Location, Product, Warehouse } from '../types';

export default function InventoryTransferPage() {
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [locations, setLocations] = useState<Location[]>([]);
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
    listLocations().then(setLocations).catch(() => undefined);
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!product) {
      setError('Seleccione un producto');
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
      <PageHeader title="Transferencia de inventario" subtitle="Mueve stock entre ubicaciones" />

      {notice && (
        <div className="mb-3 rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-700">{notice}</div>
      )}
      {error && <ErrorBox message={error} />}

      <form onSubmit={submit} className="card space-y-3">
        <ProductPicker value={product} onChange={setProduct} />
        <SelectField
          label="Bodega"
          value={warehouseId}
          onChange={setWarehouseId}
          options={warehouses.map((w) => ({ value: w.id, label: w.name }))}
          required
        />
        <SelectField
          label="Ubicación origen"
          value={fromLocation}
          onChange={setFromLocation}
          options={locations.map((l) => ({ value: l.id, label: l.code }))}
          required
        />
        <SelectField
          label="Ubicación destino"
          value={toLocation}
          onChange={setToLocation}
          options={locations.map((l) => ({ value: l.id, label: l.code }))}
          required
        />
        <Field label="Cantidad" type="number" value={quantity} onChange={setQuantity} required />
        <button type="submit" className="btn-primary w-full" disabled={busy}>
          {busy ? 'Transfiriendo…' : 'Transferir'}
        </button>
      </form>
    </div>
  );
}
