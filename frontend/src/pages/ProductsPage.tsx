import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { CheckCheck, ChevronRight, Plus, Upload, X } from 'lucide-react';
import {
  addBarcode,
  createProduct,
  getProductByBarcode,
  importCatalog,
  listProducts,
  type CatalogImportReport,
} from '../api/products';
import { errorMessage } from '../api/http';
import { Empty, ErrorBox, LoadingRows, PageHeader } from '../components/Async';
import DataTable, { MobileCardList, type Column } from '../components/DataTable';
import { Field } from '../components/Form';
import Pager from '../components/Pager';
import SearchInput from '../components/SearchInput';
import StatusBadge from '../components/StatusBadge';
import { ERP_CREATE_ENABLED } from '../config';
import { isSupervisor, useAuth } from '../store/auth';
import type { Product } from '../types';

const PAGE = 50;
const EMPTY_NEW = {
  sku: '',
  name: '',
  category: '',
  unit: 'UN',
  brand: '',
  barcode: '',
  sale_price: '',
};

export default function ProductsPage() {
  const { currentUser } = useAuth();
  const canImport = isSupervisor(currentUser?.role);
  const [importing, setImporting] = useState(false);
  const [products, setProducts] = useState<Product[]>([]);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState('');
  const [barcodeSearch, setBarcodeSearch] = useState('');
  // Con una búsqueda por código de barras la lista deja de ser el catálogo.
  const [barcodeResult, setBarcodeResult] = useState(false);
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
      setBarcodeResult(false);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  function runSearch() {
    setNotice(null);
    load(search.trim() || undefined, 0);
  }

  async function handleBarcodeLookup() {
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
      setBarcodeResult(true);
      setNotice(`Producto encontrado por código de barras: ${product.sku}`);
    } catch (err) {
      const ax = err as { response?: { status?: number } };
      if (ax.response?.status === 404) {
        setProducts([]);
        setOffset(0);
        setTotal(0);
        setBarcodeResult(true);
        setNotice(`Ningún producto tiene el código ${code}.`);
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
        `Catálogo actualizado: ${rep.created ?? 0} creados · ${rep.updated ?? 0} actualizados · ${
          rep.barcodes_added ?? 0
        } códigos`
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

  function BarcodeCell({ p }: { p: Product }) {
    return (
      <div>
        {p.barcodes?.length ? (
          <div className="flex flex-wrap gap-1">
            {p.barcodes.map((b, i) => (
              <span key={i} className="badge bg-slate-100 font-mono text-slate-700">
                {b.barcode}
                {b.type ? ` (${b.type})` : ''}
              </span>
            ))}
          </div>
        ) : (
          <span className="text-xs text-amber-800">Sin código: no se puede escanear</span>
        )}
        {addingFor === p.id && (
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <input
              value={newBarcode}
              onChange={(e) => setNewBarcode(e.target.value)}
              placeholder="Nuevo código"
              className="input max-w-[10rem]"
              aria-label="Nuevo código de barras"
            />
            <input
              value={newBarcodeType}
              onChange={(e) => setNewBarcodeType(e.target.value)}
              placeholder="Tipo (opc.)"
              className="input max-w-[8rem]"
              aria-label="Tipo de código"
            />
            <button onClick={() => handleAddBarcode(p.id)} className="btn-success btn-sm">
              Guardar
            </button>
            <button onClick={() => setAddingFor(null)} className="btn-secondary btn-sm">
              Cancelar
            </button>
          </div>
        )}
      </div>
    );
  }

  const columns: Column<Product>[] = [
    { key: 'sku', header: 'SKU', render: (p) => <span className="code-strong">{p.sku}</span> },
    {
      key: 'name',
      header: 'Nombre',
      render: (p) => (
        <span>
          <Link to={`/products/${p.id}`} className="font-medium text-brand hover:underline">
            {p.name}
          </Link>
          {p.category && <span className="block text-xs text-slate-500">{p.category}</span>}
        </span>
      ),
    },
    { key: 'brand', header: 'Marca', secondary: true, render: (p) => p.brand ?? '—' },
    { key: 'unit', header: 'Unidad', secondary: true, render: (p) => p.unit ?? '—' },
    { key: 'barcodes', header: 'Códigos de barras', render: (p) => <BarcodeCell p={p} /> },
    {
      key: 'status',
      header: 'Estado',
      render: (p) => <StatusBadge status={p.is_active === false ? 'inactive' : 'active'} />,
    },
    {
      key: 'actions',
      header: '',
      align: 'right',
      render: (p) =>
        addingFor !== p.id ? (
          <button
            onClick={() => {
              setAddingFor(p.id);
              setNewBarcode('');
              setNewBarcodeType('');
            }}
            className="btn-secondary btn-sm whitespace-nowrap"
          >
            <Plus className="h-3.5 w-3.5" aria-hidden="true" />
            Código
          </button>
        ) : null,
    },
  ];

  return (
    <div>
      <PageHeader
        title="Productos"
        subtitle="Catálogo y códigos de barras"
        actions={
          <>
            {canImport && (
              <label className="btn-secondary cursor-pointer whitespace-nowrap">
                <Upload className="h-4 w-4" aria-hidden="true" />
                {importing ? 'Importando…' : 'Importar Excel'}
                <input
                  type="file"
                  accept=".xlsx,.xlsm,.xls,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel"
                  onChange={handleImport}
                  disabled={importing}
                  className="hidden"
                />
              </label>
            )}
            {ERP_CREATE_ENABLED && (
              <button onClick={() => setShowCreate((v) => !v)} className="btn-primary">
                {showCreate ? (
                  <>
                    <X className="h-4 w-4" aria-hidden="true" />
                    Cerrar
                  </>
                ) : (
                  <>
                    <Plus className="h-4 w-4" aria-hidden="true" />
                    Nuevo producto
                  </>
                )}
              </button>
            )}
          </>
        }
      />

      {ERP_CREATE_ENABLED && showCreate && (
        <form onSubmit={handleCreate} className="card mb-4 grid grid-cols-1 gap-3 md:grid-cols-2">
          <Field label="SKU *" value={np.sku} onChange={(v) => setNp({ ...np, sku: v })} required />
          <Field
            label="Nombre *"
            value={np.name}
            onChange={(v) => setNp({ ...np, name: v })}
            required
          />
          <Field
            label="Categoría"
            value={np.category}
            onChange={(v) => setNp({ ...np, category: v })}
          />
          <Field label="Marca" value={np.brand} onChange={(v) => setNp({ ...np, brand: v })} />
          <Field label="Unidad" value={np.unit} onChange={(v) => setNp({ ...np, unit: v })} />
          <Field
            label="Código de barras (opc.)"
            value={np.barcode}
            onChange={(v) => setNp({ ...np, barcode: v })}
          />
          <Field
            label="Precio venta (opc.)"
            type="number"
            value={np.sale_price}
            onChange={(v) => setNp({ ...np, sale_price: v })}
          />
          <div className="flex items-end">
            <button type="submit" className="btn-success w-full" disabled={creating}>
              {creating ? 'Creando…' : 'Crear producto'}
            </button>
          </div>
        </form>
      )}

      <div className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-2">
        <SearchInput
          label="Buscar en el catálogo"
          value={search}
          onChange={setSearch}
          onSubmit={runSearch}
          placeholder="Nombre o SKU…"
        />
        <SearchInput
          label="Buscar por código de barras"
          value={barcodeSearch}
          onChange={setBarcodeSearch}
          onSubmit={handleBarcodeLookup}
          placeholder="Escanea o escribe el código…"
        />
      </div>

      {notice && (
        <div className="mb-3 flex items-start gap-2 rounded-card border border-brand-border bg-brand-soft px-3 py-2 text-sm text-brand-darker">
          <CheckCheck className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          {notice}
        </div>
      )}
      {error && <ErrorBox message={error} />}

      {barcodeResult && (
        <button
          onClick={() => {
            setBarcodeSearch('');
            setNotice(null);
            load(search.trim() || undefined, 0);
          }}
          className="btn-secondary btn-sm mb-3"
        >
          Volver al catálogo completo
        </button>
      )}

      {loading ? (
        <LoadingRows />
      ) : products.length === 0 ? (
        <Empty
          label="No hay productos"
          hint={
            barcodeResult
              ? 'Ningún producto tiene ese código de barras.'
              : 'El catálogo se carga con «Importar Excel».'
          }
        />
      ) : (
        <>
          <div className="hidden lg:block">
            <DataTable columns={columns} rows={products} keyOf={(p) => p.id} />
          </div>
          <div className="lg:hidden">
            <MobileCardList
              rows={products}
              keyOf={(p) => p.id}
              render={(p) => (
                <div>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="code-strong">{p.sku}</span>
                    <StatusBadge status={p.is_active === false ? 'inactive' : 'active'} />
                  </div>
                  <Link
                    to={`/products/${p.id}`}
                    className="mt-0.5 flex items-center gap-1 font-medium text-brand"
                  >
                    <span className="min-w-0 truncate">{p.name}</span>
                    <ChevronRight className="h-4 w-4 shrink-0" aria-hidden="true" />
                  </Link>
                  <p className="mt-0.5 text-xs text-slate-500">
                    {[p.brand, p.category, p.unit].filter(Boolean).join(' · ') || 'Sin datos'}
                  </p>
                  <div className="mt-2">
                    <BarcodeCell p={p} />
                  </div>
                  {addingFor !== p.id && (
                    <button
                      onClick={() => {
                        setAddingFor(p.id);
                        setNewBarcode('');
                        setNewBarcodeType('');
                      }}
                      className="btn-secondary btn-sm mt-2"
                    >
                      <Plus className="h-3.5 w-3.5" aria-hidden="true" />
                      Código
                    </button>
                  )}
                </div>
              )}
            />
          </div>
        </>
      )}

      <div className="mt-3">
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
