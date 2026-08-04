import axios from 'axios';
import type { PublicBultoView } from '../types';

const baseURL = (import.meta.env.VITE_API_URL ?? 'http://localhost:8000') + '/api/v1';

// Instancia propia SIN interceptores: no adjunta el JWT ni redirige a /login ante 401.
// La página del QR es pública y la puede abrir alguien sin sesión.
const publicHttp = axios.create({ baseURL, headers: { 'Content-Type': 'application/json' } });

export async function getPublicBulto(token: string): Promise<PublicBultoView> {
  const { data } = await publicHttp.get<PublicBultoView>(
    `/public/bultos/${encodeURIComponent(token)}`
  );
  return data;
}
