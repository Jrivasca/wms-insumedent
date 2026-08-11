# Diseño de notificaciones — Selarix WMS

Estado: **propuesta de diseño** (sin implementar). Fecha: 2026-08-11.
Decidido con el usuario: en esta sesión solo se diseña; la implementación va en una
sesión posterior. Relacionado: backlog sección 0, aislamiento por tenant
(`app/core/tenant_db.py`).

## 1. Objetivo

Avisar de forma proactiva tres eventos del flujo de bodega:

1. **Nuevo pedido** — entra un pedido al WMS (manual, import PDF/OCR o sync ERP).
2. **Pedido despachado** — se confirma el despacho de un pedido.
3. **Stock 0** — un producto queda sin existencias.

Ideal: **push al teléfono** aunque la app esté cerrada (el frontend ya es PWA con
`vite-plugin-pwa`).

## 2. Arquitectura recomendada (2 fases)

Separar **generación del evento** (backend, igual en ambas fases) de la **entrega**
(in-app primero, push después). Así los disparadores quedan listos y auditables desde
la Fase 1, y el Web Push se agrega encima sin re-tocar la lógica de negocio.

```
evento de negocio ─▶ notification_service.emit(tenant_id, type, audiencia, payload)
                         │
                         ├─ persiste en colección `notifications`  (Fase 1)  ─▶ feed in-app / campana
                         └─ envía Web Push a las suscripciones     (Fase 2)  ─▶ notificación en el teléfono
```

- **Fase 1 — Feed in-app**: colección `notifications` + hooks en los 3 eventos +
  endpoints de lectura + campana con contador en el header. Sin permisos de sistema
  operativo; funciona mientras la app está abierta. Barato y de bajo riesgo.
- **Fase 2 — Web Push (VAPID)**: `service worker` + suscripciones por usuario +
  envío con `pywebpush`. Push real al teléfono con la app cerrada.

Descartado por ahora: canales de terceros (Telegram/WhatsApp/FCM/OneSignal). Telegram
sería lo más rápido para un grupo interno, pero mete una dependencia externa y un canal
fuera de la app; se puede sumar luego como "canal" adicional del mismo `emit()`.

## 3. Multi-tenant y auditoría (requisito)

- **Todas** las escrituras/lecturas de notificaciones pasan por `tenant_db(tenant_id)`
  (igual que el resto de los servicios tras el ítem 1). Nunca `get_database()` crudo.
- Los destinatarios se resuelven **dentro del tenant** (por rol o id de usuario).
- El envío de Web Push corre en el worker o en un `BackgroundTask`; el `tenant_id` viaja
  en el documento de notificación (mismo patrón que `sync_jobs`).

## 4. Modelo de datos

### `notifications` (Fase 1)
```jsonc
{
  "tenant_id": "…",
  "type": "order_created | order_dispatched | stock_zero",
  "title": "Nuevo pedido 1042",
  "body": "Clínica Dental Demo — 5 líneas",
  "entity_type": "order | product",
  "entity_id": "…",
  "audience": { "roles": ["admin","supervisor"], "user_ids": [] },  // a quién aplica
  "read_by": ["userId1"],          // marcado por-usuario (una notif por rol → varios lectores)
  "metadata": { "erp_order_number": "1042", "warehouse_id": "…" },
  "created_by": "userId | system",
  "created_at": "…"
}
```
Índices: `(tenant_id, created_at desc)`, `(tenant_id, type, created_at desc)`.
Alternativa (más simple de consultar "no leídas por usuario"): **fan-out** — una fila
por destinatario con `user_id` + `read_at`. Recomendado si el volumen es bajo (lo es):
consulta trivial `{"tenant_id", "user_id", "read_at": null}`. **Decisión abierta 6.1.**

### `push_subscriptions` (Fase 2)
```jsonc
{
  "tenant_id": "…",
  "user_id": "…",
  "endpoint": "https://…",
  "keys": { "p256dh": "…", "auth": "…" },   // datos del navegador (no secretos del server)
  "user_agent": "…",
  "created_at": "…", "last_used_at": "…"
}
```
Índice único `(tenant_id, user_id, endpoint)`.

## 5. Puntos de integración en el código

Un solo helper `notification_service.emit(...)` invocado en cada choke point:

| Evento | Dónde | Nota |
|---|---|---|
| Nuevo pedido | `order_service.create_order_from_lines` (import PDF/OCR); ruta `POST /orders` en `api/routes/orders.py::create_order` (manual); `integrations/defontana/order_sync.sync_orders` (ERP) | Hay **3 vías** de alta. Idealmente unificar la creación manual en `create_order_from_lines` para tener **un** choke point; hoy la ruta manual duplica la lógica. |
| Pedido despachado | `dispatch_service.confirm_dispatch` (tras pasar la orden a `dispatched`) | Evento de negocio = confirmación. Si se quiere "confirmado en Defontana", mover al worker `_handle_dispatch_order`. |
| Stock 0 | `inventory_service.change_location_stock` | **Único choke point** de todo cambio de stock (regla 8.4). Disparar cuando el saldo cruza de >0 a ≤0. Ver decisión 6.2 (por ubicación vs total del producto). |

## 6. Decisiones abiertas (a cerrar antes de implementar)

1. **Modelo de lectura**: una notif por evento con `read_by[]`, **o** fan-out por
   destinatario con `read_at`. Recomiendo **fan-out** (consulta de "no leídas" trivial,
   volumen bajo).
2. **"Stock 0" = ¿por ubicación o total del producto en la bodega?** Recomiendo
   **total del producto por bodega** (más significativo). Cuesta un `aggregate`/suma
   tras cada movimiento; `change_location_stock` está en el hot path de picking/packing,
   así que conviene calcularlo solo cuando el saldo de **esa** ubicación llega a 0 y
   recién ahí sumar el total. Evitar N alertas repetidas: marcar el producto como
   "ya alertado" hasta que reingrese stock (dedupe por `(product_id, warehouse_id)`).
3. **Audiencia por evento** (propuesta inicial, configurable por tenant a futuro):
   - Nuevo pedido → `admin`, `supervisor`, `picker` ("hay trabajo").
   - Despachado → `admin`, `supervisor`, `sales` (vendedor/creador).
   - Stock 0 → `admin`, `supervisor` (reposición).
4. **Cadencia del feed in-app**: polling cada 30–60 s del contador de no leídas, o SSE
   (`text/event-stream`). Polling es más simple y suficiente al volumen actual.
5. **Fase 2 – Web Push**: generar par de claves **VAPID** (config `VAPID_PUBLIC_KEY`,
   `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT`), agregar `pywebpush` al backend, `service worker`
   + flujo de permiso en el frontend PWA. Limpiar suscripciones que devuelven 404/410.

## 7. API propuesta (Fase 1)

- `GET /api/v1/notifications?unread=true&limit=50` — lista del usuario (scoped a tenant + rol/id).
- `GET /api/v1/notifications/unread-count` — para el badge de la campana.
- `POST /api/v1/notifications/{id}/read` — marcar leída.
- `POST /api/v1/notifications/read-all` — marcar todas leídas.

Fase 2:
- `POST /api/v1/push/subscribe` / `DELETE /api/v1/push/subscribe` — alta/baja de suscripción del navegador.
- `GET /api/v1/push/vapid-public-key` — clave pública para el `service worker`.

## 8. Plan de implementación

- **Fase 1 (in-app)**: modelo + `notification_service` (emit/list/mark) + 3 hooks +
  4 endpoints + campana en el frontend. Riesgo bajo; todo detrás de `tenant_db`.
- **Fase 2 (Web Push)**: `push_subscriptions` + VAPID + `pywebpush` + `service worker` +
  permiso en la PWA + envío desde `emit()` (mejor vía worker/BackgroundTask para no
  bloquear la request).

## 9. Riesgos / notas

- **Hot path**: el hook de stock-0 vive en el motor de inventario; mantenerlo O(1) salvo
  cuando una ubicación llega a 0 (ver 6.2), y con dedupe para no spamear.
- **Idempotencia**: en la vía ERP (`order_sync`) un re-sync no debe re-notificar pedidos
  ya vistos (emitir solo en el `else`/creación, no en update).
- **Privacidad Web Push**: el payload viaja por el push service del navegador; no incluir
  datos sensibles, solo lo justo para el título/cuerpo.
