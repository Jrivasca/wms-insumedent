import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  addBarcode,
  createProduct,
  getProductByBarcode,
  importCatalog,
  listProducts,
  type CatalogImportReport,
} from '../api/products';
import { errorMessage } from '../api/http';
import { Empty, ErrorBox, Loading, PageHeader } from '../components/Async';
import { Field } from '../components/Form';
import Pager from '../components/Pager';
import { ERP_CREATE_ENABLED } from '../config';
import { isSupervisor, useAuth } from '../store/auth';
import type { Product } from '../types';

const PAGE = 50;
const EMPTY_NEW = { sku: '', name: '', category: '', unit: 'UN', brand: '', barcode: '', sale_price: '' };

export default function ProductsPage() {
  const navigate = useNavigate();
  const { currentUser } = useAuth();
  const canImport = isSupervisor(currentUser?.role);
  const [importing, setImporting] = useState(false);
  const [products, setProducts] = useState<Product[]>([]);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState('');
  const [barcodeSearch, setBarcodeSearch] = useState('');
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // add-barcode state
  const [addingFor, setAddingFor] = useState<string | null>(null);
  const [newBarcode, setNewBarcode] = useState('');
  const [newBarcodeType, setNewBarcodeType] = useState('');

  // create-product state
  const [showCreate, setShowCreate] = useState(false);
  const [np, setNp] = useState({ ...EMPTY_NEW });
  const [creating, setCreating] = useState(false);

  async function load(searchTerm?: string, off = 0) {
    setLoading(true);
    setError(null);
    try {
      const p = await listProducts(searchTerm, PAGE, off);
      setProducts(p.items);
      setTotal(p.total);
      setOffset(off);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    setNotice(null);
    load(search.trim() || undefined, 0);
  }

  async function handleBarcodeLookup(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setNotice(null);
    const code = barcodeSearch.trim();
    if (!code) return;
    setLoading(true);
    try {
      const product = await getProductByBarcode(code);
      setProducts([product]);
      setOffset(0);
      setTotal(1);
      setNotice(`Producto encontrado por código de barras: ${product.sku}`);
    } catch (err) {
      const ax = err as { response?: { status?: number } };
      if (ax.response?.status === 404) {
        setProducts([]);
        setOffset(0);
        setTotal(0);
        setNotice(`No existe producto con código ${code}`);
      } else {
        setError(errorMessage(err));
      }
    } finally {
      setLoading(false);
    }
  }

  async function handleAddBarcode(productId: string) {
    if (!newBarcode.trim()) return;
    try {
      await addBarcode(productId, newBarcode.trim(), newBarcodeType.trim() || undefined);
      setNewBarcode('');
      setNewBarcodeType('');
      setAddingFor(null);
      setNotice('Código de barras agregado');
      load(search.trim() || undefined, offset);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setNotice(null);
    setCreating(true);
    try {
      const created = await createProduct({
        sku: np.sku.trim(),
        name: np.name.trim(),
        category: np.category.trim() || undefined,
        unit: np.unit.trim() || 'UN',
        brand: np.brand.trim() || undefined,
        barcode: np.barcode.trim() || undefined,
        sale_price: np.sale_price ? Number(np.sale_price) : undefined,
      });
      setNotice(`Producto creado: ${created.sku}`);
      setNp({ ...EMPTY_NEW });
      setShowCreate(false);
      load(undefined, 0);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setCreating(false);
    }
  }

  async function handleImport(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    setError(null);
    setNotice(null);
    setImporting(true);
    try {
      const rep = await importCatalog(file);
      setNotice(
        `Catálogo actualizado: ${rep.created ?? 0} creados · ${rep.updated ?? 0} actualizados · ${rep.barcodes_added ?? 0} códigos`
      );
      load(undefined, 0);
    } catch (err) {
      const ax = err as { response?: { data?: { detail?: CatalogImportReport } } };
      const rep = ax.response?.data?.detail;
      if (rep?.error) setError(`Catálogo rechazado: ${rep.error}`);
      else setError(errorMessage(err));
    } finally {
      setImporting(false);
    }
  }

  return (
    <div>
      <PageHeader
        title="Productos"
        subtitle="Catálogo y códigos de barras"
        actions={
          <div className="flex flex-wrap gap-2">
            {canImport && (
              <label className="btn-secondary cursor-pointer whitespace-nowrap">
                {importing ? 'Importando…' : 'Importar Excel'}
                <input
                  type="file"
                  accept=".xlsx,.xlsm,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                  onChange={handleImport}
                  disabled={importing}
                  className="hidden"
                />
              </label>
            )}
            {ERP_CREATE_ENABLED && (
              <button onClick={() => setShowCreate((v) => !v)} className="btn-primary">
                {showCreate ? 'Cerrar' : '+ Nuevo producto'}
              </button>
            )}
          </div>
        }
      />

      {ERP_CREATE_ENABLED && showCreate && (
        <form onSubmit={handleCreate} className="card mb-4 grid grid-cols-1 gap-3 md:grid-cols-2">
          <Field label="SKU *" value={np.sku} onChange={(v) => setNp({ ...np, sku: v })} required />
          <Field label="Nombre *" value={np.name} onChange={(v) => setNp({ ...np, name: v })} required />
          <Field label="Categoría" value={np.category} onChange={(v) => setNp({ ...np, category: v })} />
          <Field label="Marca" value={np.brand} onChange={(v) => setNp({ ...np, brand: v })} />
          <Field label="Unidad" value={np.unit} onChange={(v) => setNp({ ...np, unit: v })} />
          <Field label="Código de barras (opc.)" value={np.barcode} onChange={(v) => setNp({ ...np, barcode: v })} />
          <Field label="Precio venta (opc.)" type="number" value={np.sale_price} onChange={(v) => setNp({ ...np, sale_price: v })} />
          <div className="flex items-end">
            <button type="submit" className="btn-success w-full" disabled={creating}>
              {creating ? 'Creando…' : 'Crear producto'}
            </button>
          </div>
        </form>
      )}

      <div className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-2">
        <form onSubmit={handleSearch} className="flex gap-2">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Buscar por nombre, SKU…"
            className="input"
          />
          <button type="submit" className="btn-primary whitespace-nowrap">
            Buscar
          </button>
        </form>

        <form onSubmit={handleBarcodeLookup} className="flex gap-2">
          <input
            value={barcodeSearch}
            onChange={(e) => setBarcodeSearch(e.target.value)}
            placeholder="Buscar por código de barras…"
            className="input"
          />
          <button type="submit" className="btn-secondary whitespace-nowrap">
            Por código
          </button>
        </form>
      </div>

      {notice && (
        <div className="mb-3 rounded-md bg-blue-50 px-3 py-2 text-sm text-blue-700">{notice}</div>
      )}
      {error && <ErrorBox message={error} />}

      {loading ? (
        <Loading />
      ) : products.length === 0 ? (
        <Empty label="No hay productos" />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="table w-full">
            <thead className="bg-slate-50">
              <tr>
                <th>SKU</th>
                <th>Nombre</th>
                <th>Marca</th>
                <th>Unidad</th>
                <th>Códigos de barras</th>
                <th>Estado</th>
                <th></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {products.map((p) => (
                <tr key={p.id} className="align-top">
                  <td className="font-mono text-xs">{p.sku}</td>
                  <td>
                    <button
                      onClick={() => navigate(`/products/${p.id}`)}
                      className="text-left font-medium text-brand hover:underline"
                    >
                      {p.name}
                    </button>
                    {p.category && <div className="text-xs text-slate-400">{p.category}</div>}
                  </td>
                  <td>{p.brand ?? '—'}</td>
                  <td>{p.unit ?? '—'}</td>
                  <td>
                    {p.barcodes?.length ? (
                      <div className="flex flex-wrap gap-1">
                        {p.barcodes.map((b, i) => (
                          <span key={i} className="badge bg-slate-100 text-slate-700">
                            {b.barcode}
                            {b.type ? ` (${b.type})` : ''}
                          </span>
                        ))}
                      </div>
                    ) : (
                      <span className="text-xs text-slate-400">sin códigos</span>
                    )}
                    {addingFor === p.id ? (
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        <input
                          value={newBarcode}
                          onChange={(e) => setNewBarcode(e.target.value)}
                          placeholder="Nuevo código"
                          className="input max-w-[10rem]"
                        />
                        <input
                          value={newBarcodeType}
                          onChange={(e) => setNewBarcodeType(e.target.value)}
                          placeholder="Tipo (opc.)"
                          className="input max-w-[8rem]"
                        />
                        <button onClick={() => handleAddBarcode(p.id)} className="btn-success">
                          Guardar
                        </button>
                        <button onClick={() => setAddingFor(null)} className="btn-secondary">
                          Cancelar
                        </button>
                      </div>
                    ) : null}
                  </td>
                  <td>
                    {p.is_active === false ? (
                      <span className="badge bg-slate-200 text-slate-600">inactivo</span>
                    ) : (
                      <span className="badge bg-emerald-100 text-emerald-800">activo</span>
                    )}
                  </td>
                  <td>
                    {addingFor !== p.id && (
                      <button
                        onClick={() => {
                          setAddingFor(p.id);
                          setNewBarcode('');
                          setNewBarcodeType('');
                        }}
                        className="btn-secondary whitespace-nowrap"
                      >
                        + Código
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="mt-2">
        <Pager
          offset={offset}
          pageSize={PAGE}
          count={products.length}
          total={total}
          onPrev={() => load(search.trim() || undefined, Math.max(0, offset - PAGE))}
          onNext={() => load(search.trim() || undefined, offset + PAGE)}
        />
      </div>
    </div>
  );
}
