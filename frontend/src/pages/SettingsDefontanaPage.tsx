import { useEffect, useState } from 'react';
import {
  checkDefontana,
  configureDefontana,
  getDefontanaStatus,
  syncOrders,
  syncProducts,
  syncWarehouses,
} from '../api/integrations';
import type { DefontanaConfig } from '../api/integrations';
import { errorMessage } from '../api/http';
import { ErrorBox, Loading, PageHeader } from '../components/Async';
import StatusBadge from '../components/StatusBadge';
import type { DefontanaStatus } from '../types';

export default function SettingsDefontanaPage() {
  const [status, setStatus] = useState<DefontanaStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  // Valores que acepta el backend (ErpEnvironment / ErpAuthMode).
  const [form, setForm] = useState<DefontanaConfig>({
    environment: 'test',
    client: '',
    company: '',
    user: '',
    password: '',
    email: '',
    email_password: '',
    auth_mode: 'client_company_user',
  });
  const emailLogin = form.auth_mode === 'email_login';

  async function loadStatus() {
    setLoading(true);
    setError(null);
    try {
      const s = await getDefontanaStatus();
      setStatus(s);
      setForm((f) => ({
        ...f,
        environment: s.environment ?? f.environment,
        auth_mode: s.auth_mode ?? f.auth_mode,
      }));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadStatus();
  }, []);

  function update<K extends keyof DefontanaConfig>(key: K, value: string) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function handleConfigure(e: React.FormEvent) {
    e.preventDefault();
    setBusy('configure');
    setError(null);
    setNotice(null);
    try {
      // Only send filled fields of the chosen auth mode, to avoid overwriting with blanks
      // (an empty password keeps the stored one).
      const payload: DefontanaConfig = {
        environment: form.environment,
        auth_mode: form.auth_mode,
      };
      const fields: (keyof DefontanaConfig)[] = emailLogin
        ? ['email', 'email_password']
        : ['client', 'company', 'user', 'password'];
      for (const k of fields) {
        const v = form[k];
        if (typeof v === 'string' && v.trim()) payload[k] = v.trim();
      }
      const s = await configureDefontana(payload);
      setStatus(s);
      setNotice('Configuración guardada');
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function handleCheck() {
    setBusy('check');
    setError(null);
    setNotice(null);
    try {
      const res = await checkDefontana();
      setNotice(`Conexión: ${res.status}${res.message ? ' — ' + res.message : ''}`);
      loadStatus();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function runSync(kind: 'products' | 'warehouses' | 'orders') {
    setBusy(kind);
    setError(null);
    setNotice(null);
    try {
      const fn = kind === 'products' ? syncProducts : kind === 'warehouses' ? syncWarehouses : syncOrders;
      const res = await fn();
      setNotice(`Sincronización ${kind}: ${res.status}`);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  if (loading) return <Loading />;

  return (
    <div>
      <PageHeader title="Configuración Defontana" subtitle="Integración ERP" />

      {notice && (
        <div className="mb-3 rounded-md bg-blue-50 px-3 py-2 text-sm text-blue-700">{notice}</div>
      )}
      {error && <ErrorBox message={error} />}

      <div className="card mb-4">
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-sm text-slate-500">Estado:</span>
          <StatusBadge status={status?.status ?? 'desconocido'} />
          {status?.mock && <span className="badge bg-slate-100 text-slate-600">mock</span>}
          {status?.environment && (
            <span className="text-sm text-slate-500">Entorno: {status.environment}</span>
          )}
          {status?.base_url && (
            <span className="font-mono text-xs text-slate-400">{status.base_url}</span>
          )}
          {status?.last_check_at && (
            <span className="text-xs text-slate-400">
              Última verificación: {new Date(status.last_check_at).toLocaleString()}
            </span>
          )}
        </div>
        {status?.last_error && <p className="mt-2 text-sm text-red-600">{status.last_error}</p>}
        {status?.mock && (
          <p className="mt-3 rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-800">
            Modo simulado activo (<code>DEFONTANA_MOCK=true</code>): la verificación y las
            sincronizaciones usan datos de prueba y no contactan a Defontana. Para conectar de
            verdad, pon <code>DEFONTANA_MOCK=false</code> en el <code>.env</code> y reinicia backend
            y worker.
          </p>
        )}

        <div className="mt-3 flex flex-wrap gap-2">
          <button onClick={handleCheck} className="btn-secondary" disabled={busy === 'check'}>
            {busy === 'check' ? 'Verificando…' : 'Verificar conexión'}
          </button>
          <button onClick={() => runSync('products')} className="btn-primary" disabled={busy === 'products'}>
            {busy === 'products' ? '…' : 'Sync productos'}
          </button>
          <button onClick={() => runSync('warehouses')} className="btn-primary" disabled={busy === 'warehouses'}>
            {busy === 'warehouses' ? '…' : 'Sync bodegas'}
          </button>
          <button onClick={() => runSync('orders')} className="btn-primary" disabled={busy === 'orders'}>
            {busy === 'orders' ? '…' : 'Sync pedidos'}
          </button>
        </div>
      </div>

      <form onSubmit={handleConfigure} className="card grid grid-cols-1 gap-3 md:grid-cols-2">
        <h2 className="md:col-span-2 text-lg font-semibold">Credenciales</h2>
        <div>
          <label className="label">Entorno</label>
          <select
            value={form.environment}
            onChange={(e) => update('environment', e.target.value)}
            className="input"
          >
            <option value="test">Pruebas (replapi.defontana.com)</option>
            <option value="production">Producción (api.defontana.com)</option>
          </select>
        </div>
        <div>
          <label className="label">Modo de autenticación</label>
          <select
            value={form.auth_mode}
            onChange={(e) => update('auth_mode', e.target.value)}
            className="input"
          >
            <option value="client_company_user">Cliente / Empresa / Usuario</option>
            <option value="email_login">Email</option>
          </select>
        </div>
        {emailLogin ? (
          <>
            <div>
              <label className="label">Email</label>
              <input type="email" value={form.email ?? ''} onChange={(e) => update('email', e.target.value)} className="input" />
            </div>
            <div>
              <label className="label">Contraseña</label>
              <input
                type="password"
                value={form.email_password ?? ''}
                onChange={(e) => update('email_password', e.target.value)}
                className="input"
                placeholder={status?.configured ? 'Vacío = mantener la guardada' : ''}
              />
            </div>
          </>
        ) : (
          <>
            <div>
              <label className="label">IDCliente</label>
              <input value={form.client ?? ''} onChange={(e) => update('client', e.target.value)} className="input" />
            </div>
            <div>
              <label className="label">IDEmpresa</label>
              <input value={form.company ?? ''} onChange={(e) => update('company', e.target.value)} className="input" />
            </div>
            <div>
              <label className="label">IDUsuario</label>
              <input value={form.user ?? ''} onChange={(e) => update('user', e.target.value)} className="input" />
            </div>
            <div>
              <label className="label">Contraseña</label>
              <input
                type="password"
                value={form.password ?? ''}
                onChange={(e) => update('password', e.target.value)}
                className="input"
                placeholder={status?.configured ? 'Vacío = mantener la guardada' : ''}
              />
            </div>
          </>
        )}
        <div className="md:col-span-2">
          <button type="submit" className="btn-success" disabled={busy === 'configure'}>
            {busy === 'configure' ? 'Guardando…' : 'Guardar configuración'}
          </button>
        </div>
      </form>
    </div>
  );
}
