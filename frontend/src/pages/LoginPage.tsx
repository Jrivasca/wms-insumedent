import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { errorMessage } from '../api/http';
import { isOperario, useAuth } from '../store/auth';

export default function LoginPage() {
  const { login, token, currentUser } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Already logged in.
  if (token && currentUser) {
    navigate(isOperario(currentUser.role) ? '/my/picking' : '/', { replace: true });
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const user = await login(email, password);
      navigate(isOperario(user.role) ? '/my/picking' : '/', { replace: true });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-900 p-4">
      <div className="w-full max-w-sm rounded-xl bg-white p-6 shadow-lg">
        <div className="mb-6 text-center">
          <h1 className="text-2xl font-bold text-slate-900">WMS Insumedent</h1>
          <p className="text-sm text-slate-500">Inicie sesión para continuar</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="label" htmlFor="email">
              Correo
            </label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="admin@demo.cl"
              className="input"
              required
              autoComplete="username"
            />
          </div>

          <div>
            <label className="label" htmlFor="password">
              Contraseña
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="admin123"
              className="input"
              required
              autoComplete="current-password"
            />
          </div>

          {error && (
            <div className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>
          )}

          <button type="submit" className="btn-primary w-full" disabled={busy}>
            {busy ? 'Ingresando…' : 'Ingresar'}
          </button>
        </form>

        <p className="mt-4 text-center text-xs text-slate-400">
          Demo: admin@demo.cl / admin123
        </p>
      </div>
    </div>
  );
}
