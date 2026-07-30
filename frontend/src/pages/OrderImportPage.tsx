import { Fragment, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { parseOrderPdf, confirmOrderImport, type ConfirmLine } from '../api/orderImport';
import { errorMessage } from '../api/http';
import { ErrorBox, PageHeader } from '../components/Async';
import { Field, ProductPicker } from '../components/Form';
import type { ParsedOrderLine, Product } from '../types';

interface EditLine extends ParsedOrderLine {
  include: boolean;
  resolved: Product | null;
}

const STATUS_STYLE: Record<string, string> = {
  matched: 'bg-emerald-100 text-emerald-700',
  ambiguous: 'bg-amber-100 text-amber-700',
  unmatched: 'bg-red-100 text-red-700',
  invalid: 'bg-red-100 text-red-700',
};
const STATUS_LABEL: Record<string, string> = {
  matched: 'En catálogo',
  ambiguous: 'Ambiguo',
  unmatched: 'Sin match',
  invalid: 'Revisar cantidad',
};

function MatchBadge({ status }: { status: string }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLE[status] ?? 'bg-slate-100 text-slate-600'}`}>
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

export default function OrderImportPage() {
  const navigate = useNavigate();
  const [parsing, setParsing] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [docWarnings, setDocWarnings] = useState<string[]>([]);
  const [fileName, setFileName] = useState<string | null>(null);

  // Editable header + lines (null draft = nothing parsed yet).
  const [folio, setFolio] = useState('');
  const [customer, setCustomer] = useState('');
  const [rut, setRut] = useState('');
  const [docDate, setDocDate] = useState('');
  const [docType, setDocType] = useState<string | null>(null);
  const [lines, setLines] = useState<EditLine[] | null>(null);

  async function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = ''; // allow re-selecting the same file
    if (!file) return;
    setParsing(true);
    setError(null);
    setLines(null);
    setFileName(file.name);
    try {
      const draft = await parseOrderPdf(file);
      setFolio(draft.erp_order_number ?? '');
      setCustomer(draft.customer ?? '');
      setRut(draft.customer_rut ?? '');
      setDocDate(draft.order_date ?? '');
      setDocType(draft.doc_type ?? null);
      setDocWarnings(draft.document_warnings ?? []);
      setLines(
        (draft.lines ?? []).map((l) => ({
          ...l,
          include: l.match_status !== 'invalid',
          resolved: null,
        }))
      );
    } catch (err) {
      setError(errorMessage(err));
      setFileName(null);
    } finally {
      setParsing(false);
    }
  }

  function updateLine(idx: number, patch: Partial<EditLine>) {
    setLines((ls) => (ls ? ls.map((l, i) => (i === idx ? { ...l, ...patch } : l)) : ls));
  }

  function resolveWithProduct(idx: number, p: Product | null) {
    if (p) {
      updateLine(idx, {
        resolved: p,
        product_id: p.id,
        sku: p.sku,
        name: p.name,
        match_status: 'matched',
        match_by: 'manual',
        warnings: [],
      });
    } else {
      updateLine(idx, { resolved: null, product_id: null, match_status: 'unmatched' });
    }
  }

  function pickCandidate(idx: number, productId: string) {
    const line = lines?.[idx];
    const cand = line?.candidates.find((c) => c.product_id === productId);
    if (!cand) return;
    updateLine(idx, {
      product_id: cand.product_id,
      sku: cand.sku,
      name: cand.name,
      match_status: 'matched',
      match_by: 'name',
      warnings: [],
    });
  }

  async function handleCreate() {
    if (!lines) return;
    if (!folio.trim()) {
      setError('Ingresa el N° de pedido (folio).');
      return;
    }
    const included = lines.filter((l) => l.include);
    if (included.length === 0) {
      setError('Incluye al menos una línea.');
      return;
    }
    const bad = included.filter((l) => !l.ordered_quantity || l.ordered_quantity <= 0);
    if (bad.length > 0) {
      setError('Hay líneas con cantidad inválida. Corrígelas o exclúyelas.');
      return;
    }
    const noSku = included.filter((l) => !(l.sku ?? '').trim());
    if (noSku.length > 0) {
      setError('Hay líneas sin SKU/producto. Resuélvelas con el buscador o exclúyelas.');
      return;
    }
    const orphans = included.filter((l) => !l.product_id);
    if (orphans.length > 0) {
      const ok = window.confirm(
        `${orphans.length} línea(s) no están en el catálogo. Se crearán igual (podrás resolverlas en el picking). ¿Continuar?`
      );
      if (!ok) return;
    }

    const payloadLines: ConfirmLine[] = included.map((l) => ({
      sku: (l.sku ?? '').trim(),
      name: l.name ?? undefined,
      unit: l.unit || 'UN',
      ordered_quantity: Number(l.ordered_quantity),
      product_id: l.product_id ?? undefined,
    }));

    setCreating(true);
    setError(null);
    try {
      const created = await confirmOrderImport({
        erp_order_number: folio.trim(),
        customer: customer.trim() || undefined,
        customer_rut: rut.trim() || undefined,
        order_date: docDate.trim() || undefined,
        doc_type: docType || undefined,
        lines: payloadLines,
      });
      navigate('/orders', {
        state: { notice: `Pedido ${created.erp_order_number} creado desde PDF · sincronización encolada` },
      });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setCreating(false);
    }
  }

  const includedCount = lines?.filter((l) => l.include).length ?? 0;

  return (
    <div>
      <PageHeader
        title="Importar pedido desde PDF"
        subtitle="Sube una cotización o pedido INSUMEDENT (PDF o foto), revisa las líneas y crea el pedido"
        actions={
          <button onClick={() => navigate('/orders')} className="btn-secondary">
            ← Pedidos
          </button>
        }
      />

      {error && <ErrorBox message={error} />}

      {/* Upload */}
      <div className="card mb-4">
        <label className="label">Cotización o pedido (PDF o foto)</label>
        <div className="flex flex-wrap items-center gap-3">
          <label className="btn-primary cursor-pointer">
            {parsing ? 'Leyendo…' : 'Seleccionar PDF o foto'}
            <input
              type="file"
              accept="application/pdf,.pdf,image/*"
              onChange={onFile}
              disabled={parsing}
              className="hidden"
            />
          </label>
          {fileName && <span className="text-sm text-slate-500">{fileName}</span>}
        </div>
        <p className="mt-2 text-xs text-slate-400">
          Cotización o pedido INSUMEDENT en PDF (ideal) o una foto/escaneo (JPG/PNG). Las fotos se
          leen por OCR: revisa bien el folio, el cliente y cada línea antes de crear.
        </p>
      </div>

      {docWarnings.length > 0 && (
        <div className="mb-4 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          <ul className="list-inside list-disc space-y-0.5">
            {docWarnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      {lines && (
        <>
          {docType && (
            <div className="mb-3 text-sm text-slate-600">
              Documento detectado: <span className="font-medium capitalize">{docType}</span>
              {folio && <span> · N° {folio}</span>}
            </div>
          )}
          {/* Header fields */}
          <div className="card mb-4 grid grid-cols-1 gap-3 md:grid-cols-4">
            <Field label="N° de pedido (folio) *" value={folio} onChange={setFolio} required />
            <Field label="Cliente" value={customer} onChange={setCustomer} />
            <Field label="RUT cliente" value={rut} onChange={setRut} />
            <Field label="Fecha documento" value={docDate} onChange={setDocDate} />
          </div>

          {/* Lines */}
          <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
            <table className="table w-full">
              <thead className="bg-slate-50">
                <tr>
                  <th className="w-10">Incl.</th>
                  <th className="w-10">#</th>
                  <th>SKU</th>
                  <th>Producto (detalle del PDF)</th>
                  <th className="w-24">Cant.</th>
                  <th className="w-20">Unidad</th>
                  <th>Estado</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {lines.map((l, idx) => {
                  const needsResolve = l.match_status === 'unmatched' || l.match_status === 'ambiguous';
                  return (
                    <Fragment key={idx}>
                      <tr className={l.include ? '' : 'opacity-40'}>
                        <td className="text-center">
                          <input
                            type="checkbox"
                            checked={l.include}
                            onChange={(e) => updateLine(idx, { include: e.target.checked })}
                          />
                        </td>
                        <td className="text-xs text-slate-400">{l.item ?? idx + 1}</td>
                        <td>
                          <input
                            value={l.sku ?? ''}
                            onChange={(e) => updateLine(idx, { sku: e.target.value })}
                            className="input font-mono text-xs"
                          />
                        </td>
                        <td className="text-sm">{l.name}</td>
                        <td>
                          <input
                            type="number"
                            min={0}
                            step="any"
                            value={l.ordered_quantity ?? ''}
                            onChange={(e) =>
                              updateLine(idx, {
                                ordered_quantity: e.target.value === '' ? null : Number(e.target.value),
                                match_status:
                                  l.match_status === 'invalid' && Number(e.target.value) > 0
                                    ? 'unmatched'
                                    : l.match_status,
                              })
                            }
                            className="input w-20"
                          />
                        </td>
                        <td className="text-xs">{l.unit}</td>
                        <td>
                          <MatchBadge status={l.match_status} />
                        </td>
                      </tr>

                      {(needsResolve || l.warnings.length > 0 || l.comments.length > 0) && (
                        <tr className={l.include ? '' : 'opacity-40'}>
                          <td></td>
                          <td colSpan={6} className="pb-3">
                            {l.comments.length > 0 && (
                              <p className="mb-1 text-xs italic text-slate-500">
                                Nota del PDF: {l.comments.join(' · ')}
                              </p>
                            )}
                            {l.warnings.map((w, i) => (
                              <p key={i} className="mb-1 text-xs text-amber-700">
                                ⚠ {w}
                              </p>
                            ))}
                            {l.match_status === 'ambiguous' && l.candidates.length > 0 && (
                              <select
                                className="input max-w-md"
                                defaultValue=""
                                onChange={(e) => pickCandidate(idx, e.target.value)}
                              >
                                <option value="" disabled>
                                  Elige el producto correcto…
                                </option>
                                {l.candidates.map((c) => (
                                  <option key={c.product_id} value={c.product_id}>
                                    {c.name} · {c.sku}
                                  </option>
                                ))}
                              </select>
                            )}
                            {l.match_status === 'unmatched' && (
                              <div className="max-w-md">
                                <ProductPicker
                                  value={l.resolved}
                                  onChange={(p) => resolveWithProduct(idx, p)}
                                />
                              </div>
                            )}
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="mt-4 flex items-center gap-3">
            <button onClick={handleCreate} className="btn-success" disabled={creating}>
              {creating ? 'Creando…' : `Crear pedido (${includedCount} líneas)`}
            </button>
            <span className="text-xs text-slate-400">
              El pedido se crea en estado “imported” y se encola la sincronización con el ERP.
            </span>
          </div>
        </>
      )}
    </div>
  );
}
