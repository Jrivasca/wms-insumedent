import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  AlertTriangle,
  Boxes,
  CheckCheck,
  ChevronRight,
  ClipboardList,
  Pencil,
  PlugZap,
  X,
} from 'lucide-react';
import {
  checkDefontana,
  configureDefontana,
  getDefontanaStatus,
  syncOrders,
  syncProducts,
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

function fechaHora(iso?: string | null): string {
  if (!iso) return 'nunca';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? 'nunca' : d.toLocaleString('es-CL');
}

/** Fila de dato en el bloque de sincronizaciones. */
function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex flex-wrap justify-between gap-2 py-1">
      <dt className="text-slate-500">{label}</dt>
      <dd className="text-slate-800">{value}</dd>
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

  async function runSync(kind: 'products' | 'orders') {
    setBusy(kind);
    setError(null);
    setNotice(null);
    try {
      const fn = kind === 'products' ? syncProducts : syncOrders;
      const res = await fn();
      const s = (res.summary ?? {}) as Record<string, number>;
      setNotice(
        kind === 'products'
          ? `Artículos con lote: ${s.synced ?? 0} leídos (${s.created ?? 0} nuevos, ${
              s.updated ?? 0
            } actualizados, ${s.deactivated ?? 0} desactivados) · ${s.batches ?? 0} lotes`
          : `Pedidos: ${s.created ?? 0} nuevos, ${s.updated ?? 0} actualizados, ${
              s.cancelled ?? 0
            } cancelados, ${s.flagged ?? 0} por revisar`
      );
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  if (loading) return <Loading />;

  const creds = status?.credentials;
  const savedEmailLogin = status?.auth_mode === 'email_login';
  const auto = status?.orders_auto_sync;

  return (
    <div className="max-w-3xl">
      <PageHeader title="Defontana" subtitle="Conexión con el ERP y sincronizaciones" />

      {notice && (
        <div className="mb-3 flex items-start gap-2 rounded-card border border-brand-border bg-brand-soft px-3 py-2 text-sm text-brand-darker">
          <CheckCheck className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          {notice}
        </div>
      )}
      {error && <ErrorBox message={error} onRetry={loadStatus} />}

      {/* Estado de la conexión */}
      <div className="card mb-4">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <StatusBadge status={status?.status ?? 'desconocido'} withDot />
          {status?.mock && (
            <span className="badge bg-amber-100 text-amber-900">datos de prueba</span>
          )}
          {status?.environment && (
            <span className="text-sm text-slate-600">
              {ENVIRONMENT_LABEL[status.environment] ?? status.environment}
            </span>
          )}
          {status?.base_url && <span className="code">{status.base_url}</span>}
        </div>
        <p className="mt-2 text-xs text-slate-500">
          Última verificación: {fechaHora(status?.last_check_at)}
        </p>

        {status?.last_error && (
          <div className="mt-3 flex items-start gap-2 rounded-card border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <span>
              Último error informado por Defontana: {status.last_error}
            </span>
          </div>
        )}

        {status?.mock && (
          <div className="mt-3 rounded-card border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
            Modo simulado activo (<code className="code-strong">DEFONTANA_MOCK=true</code>): la
            verificación y las sincronizaciones usan datos de prueba y no contactan a Defontana.
            Para conectar de verdad, pon <code className="code-strong">DEFONTANA_MOCK=false</code> en
            el <code className="code-strong">.env</code> y reinicia backend y worker.
          </div>
        )}

        <div className="mt-4 flex flex-wrap gap-2">
          <button onClick={handleCheck} className="btn-secondary" disabled={busy === 'check'}>
            <PlugZap className="h-4 w-4" aria-hidden="true" />
            {busy === 'check' ? 'Verificando…' : 'Verificar conexión'}
          </button>
          <button
            onClick={() => runSync('products')}
            className="btn-secondary"
            disabled={busy === 'products'}
          >
            <Boxes className="h-4 w-4" aria-hidden="true" />
            {busy === 'products' ? 'Trayendo…' : 'Traer lotes'}
          </button>
          <button
            onClick={() => runSync('orders')}
            className="btn-secondary"
            disabled={busy === 'orders'}
          >
            <ClipboardList className="h-4 w-4" aria-hidden="true" />
            {busy === 'orders' ? 'Trayendo…' : 'Traer pedidos'}
          </button>
        </div>
      </div>

      {/* Qué hace cada sincronización */}
      <div className="card mb-4">
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
          Sincronizaciones
        </h2>
        <dl className="divide-y divide-slate-100 text-sm">
          <Row label="Último stock traído" value={fechaHora(status?.last_stock_sync_at)} />
          <Row label="Últimos lotes traídos" value={fechaHora(status?.last_lots_sync_at)} />
          {auto && (
            <>
              <Row
                label="Pedidos automáticos"
                value={
                  auto.enabled
                    ? `cada ${auto.interval_minutes} min, ${auto.hours}${
                        auto.weekdays_only ? ' (lunes a viernes)' : ''
                      }`
                    : 'desactivada'
                }
              />
              <Row label="Última corrida" value={fechaHora(auto.last_run_at)} />
              {auto.last_summary && (
                <Row
                  label="Resultado"
                  value={`${auto.last_summary.created ?? 0} nuevos · ${
                    auto.last_summary.cancelled ?? 0
                  } cancelados · ${auto.last_summary.flagged ?? 0} por revisar`}
                />
              )}
            </>
          )}
        </dl>

        {auto?.last_error && (
          <p className="mt-2 flex items-start gap-1.5 text-xs text-red-700">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            Error en la última sincronización automática: {auto.last_error}
          </p>
        )}

        <p className="hint mt-3">
          «Traer lotes» lee del módulo Inventario de Defontana los artículos que manejan lotes, con
          sus lotes y vencimientos; no modifica el stock ni los códigos de barra, marca o familia.
          El catálogo completo sigue por el importador de Excel y las bodegas se administran solo en
          el WMS.
        </p>
        <Link
          to="/inventory/erp-stock"
          className="mt-2 inline-flex items-center gap-1 text-sm font-medium text-brand hover:underline"
        >
          Comparar el stock con Defontana
          <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
        </Link>
      </div>

      {/* Credenciales guardadas */}
      {!showForm && status?.configured && (
        <div className="card">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
              Credenciales
            </h2>
            <button onClick={startEdit} className="btn-secondary btn-sm">
              <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
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
          <p className="hint mt-3">
            Por seguridad las credenciales se muestran en solo lectura y la contraseña nunca se
            muestra. Usa «Editar» para cambiarlas.
          </p>
        </div>
      )}

      {/* Alta / edición de credenciales */}
      {showForm && (
        <form onSubmit={handleConfigure} className="card grid grid-cols-1 gap-3 md:grid-cols-2">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500 md:col-span-2">
            {editing ? 'Editar credenciales' : 'Credenciales'}
          </h2>
          <div>
            <label className="label" htmlFor="df-env">
              Entorno
            </label>
            <select
              id="df-env"
              value={form.environment}
              onChange={(e) => update('environment', e.target.value)}
              className="input"
            >
              <option value="test">{ENVIRONMENT_LABEL.test}</option>
              <option value="production">{ENVIRONMENT_LABEL.production}</option>
            </select>
          </div>
          <div>
            <label className="label" htmlFor="df-mode">
              Modo de autenticación
            </label>
            <select
              id="df-mode"
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
                <label className="label" htmlFor="df-email">
                  Email
                </label>
                <input
                  id="df-email"
                  type="email"
                  value={form.email ?? ''}
                  onChange={(e) => update('email', e.target.value)}
                  className="input"
                />
              </div>
              <div>
                <label className="label" htmlFor="df-email-pass">
                  Contraseña
                </label>
                <input
                  id="df-email-pass"
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
                <label className="label" htmlFor="df-client">
                  IDCliente
                </label>
                <input
                  id="df-client"
                  value={form.client ?? ''}
                  onChange={(e) => update('client', e.target.value)}
                  className="input"
                />
              </div>
              <div>
                <label className="label" htmlFor="df-company">
                  IDEmpresa
                </label>
                <input
                  id="df-company"
                  value={form.company ?? ''}
                  onChange={(e) => update('company', e.target.value)}
                  className="input"
                />
              </div>
              <div>
                <label className="label" htmlFor="df-user">
                  IDUsuario
                </label>
                <input
                  id="df-user"
                  value={form.user ?? ''}
                  onChange={(e) => update('user', e.target.value)}
                  className="input"
                />
              </div>
              <div>
                <label className="label" htmlFor="df-pass">
                  Contraseña
                </label>
                <input
                  id="df-pass"
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
            <p className="hint md:col-span-2">
              Si cambias el entorno o las credenciales, el token actual se descarta y habrá que
              verificar la conexión de nuevo.
            </p>
          )}
          <div className="flex flex-wrap gap-2 md:col-span-2">
            <button type="submit" className="btn-primary" disabled={busy === 'configure'}>
              {busy === 'configure' ? 'Guardando…' : 'Guardar configuración'}
            </button>
            {editing && (
              <button
                type="button"
                onClick={cancelEdit}
                className="btn-secondary"
                disabled={busy === 'configure'}
              >
                <X className="h-4 w-4" aria-hidden="true" />
                Cancelar
              </button>
            )}
          </div>
        </form>
      )}
    </div>
  );
}
