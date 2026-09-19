import { useEffect, useState } from 'react';
import { CheckCheck } from 'lucide-react';
import { createAdjustment } from '../api/inventory';
import { listWarehouses } from '../api/warehouses';
import { errorMessage } from '../api/http';
import { ErrorBox, PageHeader } from '../components/Async';
import { Field, ProductPicker, SelectField } from '../components/Form';
import LocationCombobox from '../components/LocationCombobox';
import type { Product, Warehouse } from '../types';

export default function InventoryAdjustmentPage() {
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
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
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!product) {
      setError('Elige el producto a ajustar.');
      return;
    }
    if (!locationId) {
      setError('Elige la ubicación del stock que estás corrigiendo.');
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

  const qty = Number(quantity);

  return (
    <div className="mx-auto max-w-xl">
      <PageHeader
        title="Ajuste de inventario"
        subtitle="Corrige el stock de una ubicación. Solo supervisores."
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
            setLocationId('');
          }}
          options={warehouses.map((w) => ({ value: w.id, label: w.name }))}
          required
        />
        <LocationCombobox
          label="Ubicación"
          value={locationId}
          onChange={setLocationId}
          warehouseId={warehouseId}
          requireWarehouse
        />
        <div>
          <Field
            label="Cantidad"
            type="number"
            value={quantity}
            onChange={setQuantity}
            placeholder="Ej: 5 agrega · -5 descuenta"
            required
          />
          {quantity !== '' && !Number.isNaN(qty) && qty !== 0 && (
            <p className={`hint ${qty > 0 ? 'text-emerald-700' : 'text-amber-800'}`}>
              {qty > 0
                ? `Se agregarán ${qty} unidades al stock de esta ubicación.`
                : `Se descontarán ${Math.abs(qty)} unidades del stock de esta ubicación.`}
            </p>
          )}
        </div>
        <Field
          label="Motivo"
          value={reason}
          onChange={setReason}
          placeholder="Ej: merma, conteo cíclico, rotura"
          required
        />
        <div className="grid grid-cols-2 gap-2">
          <Field label="Lote (opc.)" value={lot} onChange={setLot} />
          <Field label="Serie (opc.)" value={serial} onChange={setSerial} />
        </div>
        <button type="submit" className="btn-success btn-xl w-full" disabled={busy}>
          {busy ? 'Registrando…' : 'Registrar ajuste'}
        </button>
      </form>
    </div>
  );
}
