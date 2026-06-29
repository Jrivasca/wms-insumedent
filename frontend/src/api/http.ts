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

/** Extract a human-readable error message from an axios error. */
export function errorMessage(err: unknown): string {
  const ax = err as AxiosError<{ detail?: string; message?: string }>;
  if (ax?.response?.data) {
    const d = ax.response.data;
    if (typeof d === 'string') return d;
    if (d.detail) return d.detail;
    if (d.message) return d.message;
  }
  if (ax?.message) return ax.message;
  return 'Error desconocido';
}
