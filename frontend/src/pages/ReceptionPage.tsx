import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { createReception } from '../api/inventory';
import { listWarehouses, listLocations } from '../api/warehouses';
import { errorMessage } from '../api/http';
import { ErrorBox, PageHeader } from '../components/Async';
import { Field, ProductPicker, SelectField } from '../components/Form';
import EanBarcode from '../components/EanBarcode';
import type { Location, Product, Warehouse } from '../types';

export default function ReceptionPage() {
  const navigate = useNavigate();
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [locations, setLocations] = useState<Location[]>([]);
  const [product, setProduct] = useState<Product | null>(null);
  const [warehouseId, setWarehouseId] = useState('');
  const [locationId, setLocationId] = useState('');
  const [quantity, setQuantity] = useState('');
  const [reference, setReference] = useState('');
  const [lot, setLot] = useState('');
  const [expiration, setExpiration] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<{ qty: number; syncJob?: string | null } | null>(null);

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
    setDone(null);
    try {
      const res = await createReception({
        product_id: product.id,
        warehouse_id: warehouseId,
        location_id: locationId,
        quantity: Number(quantity),
        reference: reference.trim() || undefined,
        lot_number: lot.trim() || undefined,
        expiration_date: expiration || undefined,
      });
      setDone({ qty: Number(quantity), syncJob: res.sync_job_id });
      setQuantity('');
      setReference('');
      setLot('');
      setExpiration('');
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const barcode = product?.barcodes?.[0]?.barcode;

  return (
    <div className="mx-auto max-w-xl">
      <PageHeader title="Recepción de mercadería" subtitle="Ingresa stock a una ubicación y sincroniza con el ERP" />

      {error && <ErrorBox message={error} />}

      {done && (
        <div className="card mb-4 border-2 border-emerald-300 bg-emerald-50">
          <div className="font-semibold text-emerald-800">
            ✓ Recepción registrada: +{done.qty} unidades
          </div>
          <div className="mt-1 text-sm text-emerald-700">
            {done.syncJob
              ? 'Sincronización con Defontana encolada (entrada de inventario).'
              : 'Sin sincronización ERP.'}
          </div>
          <div className="mt-3">
            <button onClick={() => navigate('/labels')} className="btn-primary">
              Imprimir etiqueta →
            </button>
          </div>
        </div>
      )}

      <form onSubmit={submit} className="card space-y-3">
        <ProductPicker value={product} onChange={setProduct} />
        {barcode && (
          <div className="flex items-center gap-3 rounded-md bg-slate-50 px-3 py-2">
            <EanBarcode value={barcode} height={36} module={1.3} />
            <span className="font-mono text-xs text-slate-500">{barcode}</span>
          </div>
        )}
        <SelectField
          label="Bodega"
          value={warehouseId}
          onChange={setWarehouseId}
          options={warehouses.map((w) => ({ value: w.id, label: w.name }))}
          required
        />
        <SelectField
          label="Ubicación destino"
          value={locationId}
          onChange={setLocationId}
          options={locations.map((l) => ({ value: l.id, label: l.code }))}
          required
        />
        <Field label="Cantidad" type="number" value={quantity} onChange={setQuantity} required />
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <Field label="Lote (opc.)" value={lot} onChange={setLot} placeholder="Ej: L-2026-07" />
          <Field label="Vencimiento (opc.)" type="date" value={expiration} onChange={setExpiration} />
        </div>
        <Field
          label="Referencia (OC / guía proveedor, opc.)"
          value={reference}
          onChange={setReference}
          placeholder="Ej: OC-12345"
        />
        <button type="submit" className="btn-success w-full" disabled={busy}>
          {busy ? 'Registrando…' : 'Registrar recepción'}
        </button>
      </form>
    </div>
  );
}
