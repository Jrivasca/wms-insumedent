import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { AppNotification } from '../types';
import {
  listNotifications,
  markAllRead,
  markRead,
  unreadCount,
} from '../api/notifications';

const POLL_MS = 45_000;

const TYPE_ICON: Record<string, string> = {
  order_created: '📦',
  order_dispatched: '🚚',
  stock_zero: '⚠️',
};

function timeAgo(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '';
  const s = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (s < 60) return 'hace un momento';
  const m = Math.floor(s / 60);
  if (m < 60) return `hace ${m} min`;
  const h = Math.floor(m / 60);
  if (h < 24) return `hace ${h} h`;
  const d = Math.floor(h / 24);
  return `hace ${d} d`;
}

/** Destination for a notification's entity (order list has no per-id detail page). */
function targetFor(n: AppNotification): string | null {
  if (n.entity_type === 'product' && n.entity_id) return `/products/${n.entity_id}`;
  if (n.entity_type === 'order') return '/orders';
  return null;
}

export default function NotificationBell() {
  const navigate = useNavigate();
  const [count, setCount] = useState(0);
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<AppNotification[]>([]);
  const [loading, setLoading] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const refreshCount = useCallback(async () => {
    try {
      setCount(await unreadCount());
    } catch {
      /* silencioso: la campana no debe romper la app */
    }
  }, []);

  // Poll the unread badge.
  useEffect(() => {
    refreshCount();
    const id = window.setInterval(refreshCount, POLL_MS);
    return () => window.clearInterval(id);
  }, [refreshCount]);

  // Close on outside click.
  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [open]);

  async function loadList() {
    setLoading(true);
    try {
      const page = await listNotifications({ limit: 20 });
      setItems(page.items);
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
    }
  }

  function toggle() {
    const next = !open;
    setOpen(next);
    if (next) loadList();
  }

  async function onItemClick(n: AppNotification) {
    if (!n.read_at) {
      try {
        await markRead(n.id);
      } catch {
        /* noop */
      }
    }
    setOpen(false);
    await refreshCount();
    const to = targetFor(n);
    if (to) navigate(to);
  }

  async function onMarkAll() {
    try {
      await markAllRead();
    } catch {
      /* noop */
    }
    await Promise.all([refreshCount(), loadList()]);
  }

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={toggle}
        className="relative rounded-full p-2 hover:bg-black/10"
        aria-label="Notificaciones"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          className="h-6 w-6"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={1.8}
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M14.857 17.082a23.848 23.848 0 005.454-1.31A8.967 8.967 0 0118 9.75V9A6 6 0 006 9v.75a8.967 8.967 0 01-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 01-5.714 0m5.714 0a3 3 0 11-5.714 0"
          />
        </svg>
        {count > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-5 min-w-[1.25rem] items-center justify-center rounded-full bg-red-600 px-1 text-xs font-bold text-white">
            {count > 9 ? '9+' : count}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 z-50 mt-2 w-80 max-w-[calc(100vw-2rem)] overflow-hidden rounded-lg border border-slate-200 bg-white text-slate-800 shadow-xl">
          <div className="flex items-center justify-between border-b border-slate-100 px-4 py-2">
            <span className="text-sm font-semibold">Notificaciones</span>
            <button
              type="button"
              onClick={onMarkAll}
              className="text-xs font-medium text-brand hover:underline"
            >
              Marcar todas
            </button>
          </div>

          <div className="max-h-96 overflow-y-auto">
            {loading ? (
              <p className="px-4 py-6 text-center text-sm text-slate-400">Cargando…</p>
            ) : items.length === 0 ? (
              <p className="px-4 py-6 text-center text-sm text-slate-400">
                No tienes notificaciones.
              </p>
            ) : (
              <ul className="divide-y divide-slate-100">
                {items.map((n) => (
                  <li key={n.id}>
                    <button
                      type="button"
                      onClick={() => onItemClick(n)}
                      className={`flex w-full gap-3 px-4 py-3 text-left hover:bg-slate-50 ${
                        n.read_at ? '' : 'bg-brand/5'
                      }`}
                    >
                      <span className="text-lg leading-none">{TYPE_ICON[n.type] ?? '🔔'}</span>
                      <span className="min-w-0 flex-1">
                        <span className="flex items-center gap-2">
                          <span className="truncate text-sm font-semibold">{n.title}</span>
                          {!n.read_at && (
                            <span className="h-2 w-2 shrink-0 rounded-full bg-brand" />
                          )}
                        </span>
                        <span className="block truncate text-xs text-slate-500">{n.body}</span>
                        <span className="block text-[11px] text-slate-400">
                          {timeAgo(n.created_at)}
                        </span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
