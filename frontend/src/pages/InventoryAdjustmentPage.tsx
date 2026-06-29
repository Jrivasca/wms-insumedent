import { useEffect, useState } from 'react';
import { createAdjustment } from '../api/inventory';
import { listWarehouses, listLocations } from '../api/warehouses';
import { errorMessage } from '../api/http';
import { ErrorBox, PageHeader } from '../components/Async';
import { Field, ProductPicker, SelectField } from '../components/Form';
import type { Location, Product, Warehouse } from '../types';

export default function InventoryAdjustmentPage() {
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [locations, setLocations] = useState<Location[]>([]);
  const [product, setProduct] = useState<Product | null>(null);
  const [warehouseId, setWarehouseId] = useState('');
  const [locationId, setLocationId] = useState('');
  const [quantity, setQuantity] = useState('');
  const [reason, setReason] = useState('');
  const [lot, setLot] = useState('');
  const [serial, setSerial] = useState('');
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
      await createAdjustment({
        product_id: product.id,
        warehouse_id: warehouseId,
        location_id: locationId,
        quantity: Number(quantity),
        reason: reason.trim(),
        lot_number: lot.trim() || undefined,
        serial_number: serial.trim() || undefined,
      });
      setNotice(`Ajuste registrado: ${quantity} en ${product.sku}`);
      setQuantity('');
      setReason('');
      setLot('');
      setSerial('');
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-xl">
      <PageHeader
        title="Ajuste de inventario"
        subtitle="Corrige el stock (+/-). Requiere rol supervisor."
      />

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
          label="Ubicación"
          value={locationId}
          onChange={setLocationId}
          options={locations.map((l) => ({ value: l.id, label: l.code }))}
          required
        />
        <Field
          label="Cantidad (+ agrega, - descuenta)"
          type="number"
          value={quantity}
          onChange={setQuantity}
          required
        />
        <Field label="Motivo" value={reason} onChange={setReason} required />
        <div className="grid grid-cols-2 gap-2">
          <Field label="Lote (opc.)" value={lot} onChange={setLot} />
          <Field label="Serie (opc.)" value={serial} onChange={setSerial} />
        </div>
        <button type="submit" className="btn-success w-full" disabled={busy}>
          {busy ? 'Registrando…' : 'Registrar ajuste'}
        </button>
      </form>
    </div>
  );
}
