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

const ENVIRONMENT_LABEL: Record<string, string> = {
  test: 'Pruebas (replapi.defontana.com)',
  production: 'Producción (api.defontana.com)',
};

const AUTH_MODE_LABEL: Record<string, string> = {
  client_company_user: 'Cliente / Empresa / Usuario',
  email_login: 'Email',
};

// Valores que acepta el backend (ErpEnvironment / ErpAuthMode).
const EMPTY_FORM: DefontanaConfig = {
  environment: 'test',
  client: '',
  company: '',
  user: '',
  password: '',
  email: '',
  email_password: '',
  auth_mode: 'client_company_user',
};

/** Campo de solo lectura con el mismo aspecto que un input. */
function ReadOnlyField({ label, value }: { label: string; value?: string | null }) {
  return (
    <div>
      <label className="label">{label}</label>
      <input
        className="input cursor-default bg-slate-50 text-slate-600"
        value={value || '—'}
        readOnly
        tabIndex={-1}
      />
    </div>
  );
}

export default function SettingsDefontanaPage() {
  const [status, setStatus] = useState<DefontanaStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<DefontanaConfig>(EMPTY_FORM);
  const emailLogin = form.auth_mode === 'email_login';
  // Sin configuración todavía, el formulario se muestra directo; si ya existe, solo con "Editar".
  const showForm = !status?.configured || editing;

  async function loadStatus() {
    setLoading(true);
    setError(null);
    try {
      setStatus(await getDefontanaStatus());
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

  function startEdit() {
    const creds = status?.credentials;
    // Precarga lo guardado; las contraseñas quedan vacías (vacío = mantener la guardada).
    setForm({
      ...EMPTY_FORM,
      environment: status?.environment ?? EMPTY_FORM.environment,
      auth_mode: status?.auth_mode ?? EMPTY_FORM.auth_mode,
      client: creds?.client ?? '',
      company: creds?.company ?? '',
      user: creds?.user ?? '',
      email: creds?.email ?? '',
    });
    setNotice(null);
    setError(null);
    setEditing(true);
  }

  function cancelEdit() {
    setForm(EMPTY_FORM);
    setEditing(false);
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
      setForm(EMPTY_FORM);
      setEditing(false);
      setNotice('Configuración guardada. Usa «Verificar conexión» para probarla.');
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

  const creds = status?.credentials;
  const savedEmailLogin = status?.auth_mode === 'email_login';

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
          {/* Productos y bodegas usan Sale/* (Ventas, no contratado): solo en pruebas. */}
          {status?.sale_api_available !== false && (
            <>
              <button onClick={() => runSync('products')} className="btn-primary" disabled={busy === 'products'}>
                {busy === 'products' ? '…' : 'Sync productos'}
              </button>
              <button onClick={() => runSync('warehouses')} className="btn-primary" disabled={busy === 'warehouses'}>
                {busy === 'warehouses' ? '…' : 'Sync bodegas'}
              </button>
            </>
          )}
          <button onClick={() => runSync('orders')} className="btn-primary" disabled={busy === 'orders'}>
            {busy === 'orders' ? '…' : 'Sync pedidos'}
          </button>
        </div>
        {status?.sale_api_available === false && (
          <p className="mt-2 text-xs text-slate-500">
            Productos y bodegas no se sincronizan por API (Ventas no está contratado): usa el
            importador de Excel y el mantenedor de bodegas.
          </p>
        )}
        {status?.orders_auto_sync && (
          <p className="mt-2 text-xs text-slate-500">
            Sincronización automática de pedidos:{' '}
            {status.orders_auto_sync.enabled
              ? `cada ${status.orders_auto_sync.interval_minutes} min, ${status.orders_auto_sync.hours}${
                  status.orders_auto_sync.weekdays_only ? ' (lunes a viernes)' : ''
                }`
              : 'desactivada (DEFONTANA_ORDERS_SYNC_ENABLED)'}
            {status.orders_auto_sync.last_run_at &&
              ` · última: ${new Date(status.orders_auto_sync.last_run_at).toLocaleString()}`}
            {status.orders_auto_sync.last_summary &&
              ` · ${status.orders_auto_sync.last_summary.created ?? 0} nuevos, ${
                status.orders_auto_sync.last_summary.cancelled ?? 0
              } cancelados, ${status.orders_auto_sync.last_summary.flagged ?? 0} por revisar`}
          </p>
        )}
        {status?.orders_auto_sync?.last_error && (
          <p className="mt-1 text-xs text-red-600">
            Error en la última sincronización automática: {status.orders_auto_sync.last_error}
          </p>
        )}
      </div>

      {!showForm && status?.configured && (
        <div className="card">
          <div className="mb-3 flex items-center justify-between gap-2">
            <h2 className="text-lg font-semibold">Credenciales</h2>
            <button onClick={startEdit} className="btn-secondary">
              Editar
            </button>
          </div>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <ReadOnlyField
              label="Entorno"
              value={ENVIRONMENT_LABEL[status.environment ?? ''] ?? status.environment}
            />
            <ReadOnlyField
              label="Modo de autenticación"
              value={AUTH_MODE_LABEL[status.auth_mode ?? ''] ?? status.auth_mode}
            />
            {savedEmailLogin ? (
              <>
                <ReadOnlyField label="Email" value={creds?.email} />
                <ReadOnlyField
                  label="Contraseña"
                  value={creds?.has_email_password ? '•••••••• (guardada)' : 'Sin contraseña'}
                />
              </>
            ) : (
              <>
                <ReadOnlyField label="IDCliente" value={creds?.client} />
                <ReadOnlyField label="IDEmpresa" value={creds?.company} />
                <ReadOnlyField label="IDUsuario" value={creds?.user} />
                <ReadOnlyField
                  label="Contraseña"
                  value={creds?.has_password ? '•••••••• (guardada)' : 'Sin contraseña'}
                />
              </>
            )}
          </div>
          <p className="mt-3 text-xs text-slate-400">
            Por seguridad las credenciales se muestran en solo lectura y la contraseña nunca se
            muestra. Usa «Editar» para cambiarlas.
          </p>
        </div>
      )}

      {showForm && (
        <form onSubmit={handleConfigure} className="card grid grid-cols-1 gap-3 md:grid-cols-2">
          <h2 className="md:col-span-2 text-lg font-semibold">
            {editing ? 'Editar credenciales' : 'Credenciales'}
          </h2>
          <div>
            <label className="label">Entorno</label>
            <select
              value={form.environment}
              onChange={(e) => update('environment', e.target.value)}
              className="input"
            >
              <option value="test">{ENVIRONMENT_LABEL.test}</option>
              <option value="production">{ENVIRONMENT_LABEL.production}</option>
            </select>
          </div>
          <div>
            <label className="label">Modo de autenticación</label>
            <select
              value={form.auth_mode}
              onChange={(e) => update('auth_mode', e.target.value)}
              className="input"
            >
              <option value="client_company_user">{AUTH_MODE_LABEL.client_company_user}</option>
              <option value="email_login">{AUTH_MODE_LABEL.email_login}</option>
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
                  autoComplete="new-password"
                  placeholder={creds?.has_email_password ? 'Vacío = mantener la guardada' : ''}
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
                  autoComplete="new-password"
                  placeholder={creds?.has_password ? 'Vacío = mantener la guardada' : ''}
                />
              </div>
            </>
          )}
          {editing && (
            <p className="md:col-span-2 text-xs text-slate-500">
              Si cambias el entorno o las credenciales, el token actual se descarta y habrá que
              verificar la conexión de nuevo.
            </p>
          )}
          <div className="md:col-span-2 flex gap-2">
            <button type="submit" className="btn-success" disabled={busy === 'configure'}>
              {busy === 'configure' ? 'Guardando…' : 'Guardar configuración'}
            </button>
            {editing && (
              <button type="button" onClick={cancelEdit} className="btn-secondary" disabled={busy === 'configure'}>
                Cancelar
              </button>
            )}
          </div>
        </form>
      )}
    </div>
  );
}
