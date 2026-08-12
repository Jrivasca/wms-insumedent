import { http } from './http';

export interface VapidConfig {
  key: string;
  enabled: boolean;
}

export interface PushSubscriptionPayload {
  endpoint: string;
  keys: { p256dh: string; auth: string };
}

export async function getVapidConfig(): Promise<VapidConfig> {
  const { data } = await http.get<VapidConfig>('/push/vapid-public-key');
  return data;
}

export async function subscribePush(payload: PushSubscriptionPayload): Promise<void> {
  await http.post('/push/subscribe', payload);
}

export async function unsubscribePush(endpoint: string): Promise<void> {
  await http.post('/push/unsubscribe', { endpoint });
}
