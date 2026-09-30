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
  401: 'Su sesión expiró. Vuelva a iniciar sesión.',
  403: 'Su rol no tiene permiso para esta acción.',
  404: 'No se encontró lo que buscaba.',
  409: 'La operación choca con el estado actual (por ejemplo, un dato duplicado).',
  422: 'Hay campos incompletos o con un formato que el servidor no acepta.',
  429: 'Demasiadas solicitudes seguidas. Espere unos segundos y reintente.',
  500: 'El servidor tuvo un error inesperado. Si se repite, avise al equipo.',
  502: 'El servidor no respondió correctamente. Reintente en un momento.',
  503: 'El servicio está momentáneamente fuera de servicio. Reintente en un momento.',
  504: 'El servidor tardó demasiado en responder. Reintente.',
};

/**
 * Mensajes en inglés que NO vienen del código del WMS y por lo tanto no se pueden
 * traducir en el backend: los de Starlette (la ruta no existe) y los de Pydantic
 * (validación de tipos). Se mapean acá, que es el único lugar por donde pasan todos.
 */
const DETALLE_TRADUCIDO: Record<string, string> = {
  'Not Found': 'No se encontró lo que buscaba.',
  'Method Not Allowed': 'Esa operación no está permitida en esta dirección.',
  'Internal Server Error': 'El servidor tuvo un error inesperado. Si se repite, avise al equipo.',
  'Not authenticated': 'Su sesión expiró. Vuelva a iniciar sesión.',
};

/** Patrones de Pydantic v2. El orden importa: el primero que calza gana. */
const PYDANTIC: [RegExp, string][] = [
  [/^Field required$/i, 'este campo es obligatorio'],
  [/^Input should be a valid integer.*fractional part/i, 'debe ser un número entero, sin decimales'],
  [/^Input should be a valid integer/i, 'debe ser un número entero'],
  [/^Input should be a valid number/i, 'debe ser un número'],
  [/^Input should be a valid string/i, 'debe ser un texto'],
  [/^Input should be a valid boolean/i, 'debe ser sí o no'],
  [/^Input should be a valid date/i, 'debe ser una fecha válida'],
  [/^Input should be greater than or equal to (.+)$/i, 'debe ser mayor o igual a $1'],
  [/^Input should be greater than (.+)$/i, 'debe ser mayor que $1'],
  [/^Input should be less than or equal to (.+)$/i, 'debe ser menor o igual a $1'],
  [/^Input should be less than (.+)$/i, 'debe ser menor que $1'],
  // El caso de largo mínimo 1 va aparte: "al menos 1 caracteres" se lee mal y lo que
  // el operario necesita saber es que el campo no puede ir vacío.
  [/^String should have at least 1 characters?$/i, 'no puede quedar vacío'],
  [/^String should have at least (\d+) characters?$/i, 'debe tener al menos $1 caracteres'],
  [/^String should have at most (\d+) characters?$/i, 'no puede superar $1 caracteres'],
  [/^Value error, (.+)$/i, '$1'],
];

/** Nombres de campo del payload, tal como los ve el operario. */
const CAMPO: Record<string, string> = {
  quantity: 'Cantidad',
  reason: 'Motivo',
  ordered_quantity: 'Cantidad pedida',
  expiration_date: 'Vencimiento',
  lot_number: 'Lote',
  serial_number: 'Serie',
  product_id: 'Producto',
  warehouse_id: 'Bodega',
  location_id: 'Ubicación',
  from_location_id: 'Ubicación de origen',
  to_location_id: 'Ubicación de destino',
  sku: 'SKU',
  email: 'Correo',
  password: 'Contraseña',
  name: 'Nombre',
  role: 'Rol',
  price: 'Precio',
  erp_order_number: 'N° de pedido',
  guide_number: 'N° de guía',
  barcode: 'Código de barras',
};

function traducirPydantic(msg: string): string {
  for (const [patron, reemplazo] of PYDANTIC) {
    if (patron.test(msg)) return msg.replace(patron, reemplazo);
  }
  return msg;
}

/** Detalle de validación de FastAPI: [{loc: [...], msg: "..."}]. */
function validationMessage(detail: unknown[]): string | null {
  const parts = detail
    .map((item) => {
      if (!item || typeof item !== 'object') return null;
      const e = item as { loc?: unknown[]; msg?: string };
      if (!e.msg) return null;
      // loc viene como ["body", "campo"]: el último tramo es el campo que falló.
      const field = Array.isArray(e.loc) ? e.loc.filter((l) => typeof l === 'string').pop() : null;
      const texto = traducirPydantic(e.msg);
      if (!field || field === 'body') return texto;
      return `${CAMPO[field] ?? field}: ${texto}`;
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
      return 'El servidor tardó demasiado en responder. Reintente en un momento.';
    }
    if (ax.request) {
      return 'No se pudo contactar al servidor. Revise su conexión y reintente.';
    }
  }

  const data = ax?.response?.data;
  if (typeof data === 'string' && data.trim()) return data;
  if (data && typeof data === 'object') {
    const d = data as { detail?: unknown; message?: unknown };
    if (typeof d.detail === 'string' && d.detail.trim()) {
      return DETALLE_TRADUCIDO[d.detail.trim()] ?? d.detail;
    }
    if (Array.isArray(d.detail)) {
      const msg = validationMessage(d.detail);
      if (msg) return msg;
    }
    if (d.detail && typeof d.detail === 'object') {
      const nested = d.detail as { msg?: unknown };
      if (typeof nested.msg === 'string') return traducirPydantic(nested.msg);
    }
    if (typeof d.message === 'string' && d.message.trim()) return d.message;
  }

  const status = ax?.response?.status;
  if (status && STATUS_MESSAGE[status]) return STATUS_MESSAGE[status];
  if (status) return `El servidor respondió con un error (${status}).`;
  if (ax?.message) return ax.message;
  return 'Ocurrió un error inesperado.';
}
