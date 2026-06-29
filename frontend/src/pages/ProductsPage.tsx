import { useEffect, useState } from 'react';
import { addBarcode, getProductByBarcode, listProducts } from '../api/products';
import { errorMessage } from '../api/http';
import { Empty, ErrorBox, Loading, PageHeader } from '../components/Async';
import type { Product } from '../types';

export default function ProductsPage() {
  const [products, setProducts] = useState<Product[]>([]);
  const [search, setSearch] = useState('');
  const [barcodeSearch, setBarcodeSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // add-barcode state
  const [addingFor, setAddingFor] = useState<string | null>(null);
  const [newBarcode, setNewBarcode] = useState('');
  const [newBarcodeType, setNewBarcodeType] = useState('');

  async function load(searchTerm?: string) {
    setLoading(true);
    setError(null);
    try {
      const data = await listProducts(searchTerm);
      setProducts(data);
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
    load(search.trim() || undefined);
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
      setNotice(`Producto encontrado por código de barras: ${product.sku}`);
    } catch (err) {
      const ax = err as { response?: { status?: number } };
      if (ax.response?.status === 404) {
        setProducts([]);
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
      load(search.trim() || undefined);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <div>
      <PageHeader title="Productos" subtitle="Catálogo y códigos de barras" />

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
                    <div className="font-medium">{p.name}</div>
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
    </div>
  );
}
