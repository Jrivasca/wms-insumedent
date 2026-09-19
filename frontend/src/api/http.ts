import axios, { AxiosError } from 'axios';

export const TOKEN_KEY = 'wms_token';
export const USER_KEY = 'wms_user';

const baseURL =
  (import.meta.env.VITE_API_URL ?? 'http://localhost:8000') + '/api/v1';

export const http = axios.create({
  baseURL,
  headers: { 'Content-Type': 'application/json' },
});

http.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) {
    config.headers = config.headers ?? {};
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

http.interceptors.response.use(
  (res) => res,
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(USER_KEY);
      // Avoid redirect loop on the login page itself.
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = '/login';
      }
    }
    return Promise.reject(error);
  }
);

/** Mensaje por código cuando el backend no manda un detalle propio. */
const STATUS_MESSAGE: Record<number, string> = {
  400: 'La solicitud tiene datos inválidos.',
  401: 'Tu sesión expiró. Vuelve a iniciar sesión.',
  403: 'Tu rol no tiene permiso para esta acción.',
  404: 'No encontramos lo que buscabas.',
  409: 'La operación choca con el estado actual (por ejemplo, un dato duplicado).',
  422: 'Hay campos incompletos o con un formato que el servidor no acepta.',
  429: 'Demasiadas solicitudes seguidas. Espera unos segundos y reintenta.',
  500: 'El servidor tuvo un error inesperado. Si se repite, avisa al equipo.',
  502: 'El servidor no respondió correctamente. Reintenta en un momento.',
  503: 'El servicio está momentáneamente fuera de servicio. Reintenta en un momento.',
  504: 'El servidor tardó demasiado en responder. Reintenta.',
};

/** Detalle de validación de FastAPI: [{loc: [...], msg: "..."}]. */
function validationMessage(detail: unknown[]): string | null {
  const parts = detail
    .map((item) => {
      if (!item || typeof item !== 'object') return null;
      const e = item as { loc?: unknown[]; msg?: string };
      if (!e.msg) return null;
      // loc viene como ["body", "campo"]: el último tramo es el campo que falló.
      const field = Array.isArray(e.loc) ? e.loc.filter((l) => typeof l === 'string').pop() : null;
      return field && field !== 'body' ? `${field}: ${e.msg}` : e.msg;
    })
    .filter((p): p is string => Boolean(p));
  if (parts.length === 0) return null;
  return parts.slice(0, 3).join(' · ') + (parts.length > 3 ? ` (y ${parts.length - 3} más)` : '');
}

/**
 * Mensaje entendible a partir de un error de axios.
 *
 * Distingue tres casos que antes se mostraban igual: el servidor explicó el
 * problema (se muestra su detalle), el servidor falló sin explicar (mensaje por
 * código) y el servidor no contestó (problema de red o backend caído), que es el
 * que más confunde porque no viene de la aplicación.
 */
export function errorMessage(err: unknown): string {
  const ax = err as AxiosError<unknown>;

  // Sin respuesta: red, CORS o backend caído.
  if (ax && !ax.response) {
    if (ax.code === 'ECONNABORTED' || ax.code === 'ETIMEDOUT') {
      return 'El servidor tardó demasiado en responder. Reintenta en un momento.';
    }
    if (ax.request) {
      return 'No se pudo contactar al servidor. Revisa tu conexión y reintenta.';
    }
  }

  const data = ax?.response?.data;
  if (typeof data === 'string' && data.trim()) return data;
  if (data && typeof data === 'object') {
    const d = data as { detail?: unknown; message?: unknown };
    if (typeof d.detail === 'string' && d.detail.trim()) return d.detail;
    if (Array.isArray(d.detail)) {
      const msg = validationMessage(d.detail);
      if (msg) return msg;
    }
    if (d.detail && typeof d.detail === 'object') {
      const nested = d.detail as { msg?: unknown };
      if (typeof nested.msg === 'string') return nested.msg;
    }
    if (typeof d.message === 'string' && d.message.trim()) return d.message;
  }

  const status = ax?.response?.status;
  if (status && STATUS_MESSAGE[status]) return STATUS_MESSAGE[status];
  if (status) return `El servidor respondió con un error (${status}).`;
  if (ax?.message) return ax.message;
  return 'Ocurrió un error inesperado.';
}
