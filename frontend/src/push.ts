import type { VapidConfig } from './api/push';
import { getVapidConfig, subscribePush, unsubscribePush } from './api/push';

export type PushState = 'unsupported' | 'unconfigured' | 'denied' | 'disabled' | 'enabled';

export function isPushSupported(): boolean {
  return (
    'serviceWorker' in navigator &&
    'PushManager' in window &&
    'Notification' in window
  );
}

function urlBase64ToUint8Array(base64String: string): Uint8Array {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const raw = window.atob(base64);
  const output = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i += 1) output[i] = raw.charCodeAt(i);
  return output;
}

/** Current push state, considering client support, browser permission, server
 *  configuration and whether this device is already subscribed. */
export async function getPushState(): Promise<PushState> {
  if (!isPushSupported()) return 'unsupported';
  if (Notification.permission === 'denied') return 'denied';
  let cfg: VapidConfig;
  try {
    cfg = await getVapidConfig();
  } catch {
    return 'unconfigured';
  }
  if (!cfg.enabled || !cfg.key) return 'unconfigured';
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.getSubscription();
  return sub ? 'enabled' : 'disabled';
}

/** Request permission (if needed), subscribe this device and register it server-side. */
export async function enablePush(): Promise<PushState> {
  if (!isPushSupported()) return 'unsupported';
  const cfg = await getVapidConfig().catch(() => null);
  if (!cfg || !cfg.enabled || !cfg.key) return 'unconfigured';

  const permission = await Notification.requestPermission();
  if (permission !== 'granted') return permission === 'denied' ? 'denied' : 'disabled';

  const reg = await navigator.serviceWorker.ready;
  let sub = await reg.pushManager.getSubscription();
  if (!sub) {
    sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(cfg.key),
    });
  }
  const json = sub.toJSON();
  if (!json.endpoint || !json.keys) return 'disabled';
  await subscribePush({
    endpoint: json.endpoint,
    keys: { p256dh: json.keys.p256dh, auth: json.keys.auth },
  });
  return 'enabled';
}

/** Unsubscribe this device (browser + server). */
export async function disablePush(): Promise<PushState> {
  if (!isPushSupported()) return 'unsupported';
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.getSubscription();
  if (sub) {
    await unsubscribePush(sub.endpoint).catch(() => undefined);
    await sub.unsubscribe().catch(() => undefined);
  }
  return 'disabled';
}
