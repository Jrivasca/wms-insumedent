import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowRight, CheckCheck } from 'lucide-react';
import { createReception } from '../api/inventory';
import { listWarehouses } from '../api/warehouses';
import { errorMessage } from '../api/http';
import { ErrorBox, PageHeader } from '../components/Async';
import ConfirmDialog from '../components/ConfirmDialog';
import { Field, ProductPicker, SelectField } from '../components/Form';
import LocationCombobox from '../components/LocationCombobox';
import EanBarcode from '../components/EanBarcode';
import { errorDeCantidad } from '../lib/cantidades';
import { useBanderasErp } from '../lib/erp';
import type { Product, Warehouse } from '../types';

export default function ReceptionPage() {
  const navigate = useNavigate();
  const { inventarioViajaAlErp } = useBanderasErp();
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
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
  // Recibir mercadería ya vencida casi siempre es un error de tipeo en la fecha; el
  // backend la rechaza salvo que el operario lo confirme en este diálogo.
  const [confirmando, setConfirmando] = useState(false);

  useEffect(() => {
    listWarehouses().then(setWarehouses).catch(() => undefined);
  }, []);

  const errorCantidad = quantity === '' ? null : errorDeCantidad(quantity);
  // Fechas en local: `new Date('2020-01-01')` es UTC y en Chile cae un día antes.
  const vencida =
    expiration !== '' && new Date(`${expiration}T23:59:59`).getTime() < Date.now();

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!product) {
      setError('Seleccione el producto que está recibiendo.');
      return;
    }
    if (!locationId) {
      setError('Seleccione la ubicación donde queda la mercadería.');
      return;
    }
    const problema = errorDeCantidad(quantity);
    if (problema) {
      setError(problema);
      return;
    }
    // La recepción suma stock y puede viajar al ERP: se confirma antes de escribir.
    setError(null);
    setConfirmando(true);
  }

  async function registrar() {
    if (!product) return;
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
        allow_expired: vencida || undefined,
      });
      setDone({ qty: Number(quantity), syncJob: res.sync_job_id });
      setQuantity('');
      setReference('');
      setLot('');
      setExpiration('');
      setConfirmando(false);
    } catch (err) {
      setError(errorMessage(err));
      setConfirmando(false);
    } finally {
      setBusy(false);
    }
  }

  const barcode = product?.barcodes?.[0]?.barcode;
  const mensajeConfirmacion = [
    `Ingresa ${quantity} ${Number(quantity) === 1 ? 'unidad' : 'unidades'} de ${product?.sku ?? ''}`,
    lot.trim() ? ` (lote ${lot.trim()})` : '',
    '. ',
    vencida
      ? `Atención: el vencimiento ${expiration} ya pasó, así que la mercadería entra vencida. `
      : '',
    inventarioViajaAlErp
      ? 'Se enviará además una entrada de inventario a Defontana.'
      : 'No se envía nada al ERP: el movimiento queda solo en el WMS.',
  ].join('');

  return (
    <div className="mx-auto max-w-xl">
      <PageHeader
        title="Recepción de mercadería"
        subtitle="Ingrese stock a una ubicación; el movimiento puede viajar al ERP"
      />

      {error && <ErrorBox message={error} />}

      {done && (
        <div className="mb-4 rounded-card border border-emerald-200 bg-emerald-50 p-4">
          <div className="flex items-center gap-2 font-semibold text-emerald-900">
            <CheckCheck className="h-4 w-4" aria-hidden="true" />
            Recepción registrada: +{done.qty} unidades
          </div>
          <p className="mt-1 text-sm text-emerald-800">
            {done.syncJob
              ? 'El envío a Defontana quedó en cola (entrada de inventario).'
              : 'Sin envío al ERP.'}
          </p>
          <div className="mt-3">
            <button onClick={() => navigate('/labels')} className="btn-primary">
              Imprimir etiqueta
              <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>
        </div>
      )}

      <form onSubmit={submit} className="card space-y-3">
        <ProductPicker value={product} onChange={setProduct} />
        {barcode && (
          <div className="flex items-center gap-3 rounded-md bg-slate-50 px-3 py-2">
            <EanBarcode value={barcode} height={36} module={1.3} />
            <span className="code">{barcode}</span>
          </div>
        )}
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
          label="Ubicación destino"
          value={locationId}
          onChange={setLocationId}
          warehouseId={warehouseId}
          requireWarehouse
        />
        <Field
          label="Cantidad"
          type="number"
          inputMode="numeric"
          value={quantity}
          onChange={setQuantity}
          error={errorCantidad}
          hint="Unidades enteras."
          required
        />
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <Field label="Lote (opc.)" value={lot} onChange={setLot} placeholder="Ej: L-2026-07" />
          <Field
            label="Vencimiento (opc.)"
            type="date"
            value={expiration}
            onChange={setExpiration}
            error={vencida ? 'Esta fecha ya pasó: revísela antes de continuar.' : null}
          />
        </div>
        <Field
          label="Referencia (OC / guía proveedor, opc.)"
          value={reference}
          onChange={setReference}
          placeholder="Ej: OC-12345"
        />
        <button
          type="submit"
          className="btn-success btn-xl w-full"
          disabled={busy || errorCantidad !== null || quantity === ''}
        >
          {busy ? 'Registrando…' : 'Registrar recepción'}
        </button>
      </form>

      <ConfirmDialog
        open={confirmando}
        tone={vencida ? 'danger' : 'primary'}
        title="¿Registrar esta recepción?"
        message={mensajeConfirmacion}
        confirmLabel={vencida ? 'Recibir igual' : 'Registrar'}
        cancelLabel="Volver"
        busy={busy}
        onConfirm={registrar}
        onCancel={() => setConfirmando(false)}
      />
    </div>
  );
}
