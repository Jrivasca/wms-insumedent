# Levantamiento de requerimientos — Alertas de recepción y match de productos

> Origen: nota de voz (WhatsApp) del cliente. Interpretación y aterrizaje técnico sobre el WMS actual (`wms-insumedent`).
> Fecha: 2026-07-09

**Estado posterior de este levantamiento:** la alerta por recepción que permite retomar
pedidos parciales está implementada (`replenishment_alert_service`, notificación
`receipt_unblocks_order` y acción para preparar el faltante). Avisa cuando hay stock
pickeable suficiente para cubrir una línea completa; no avisa por cobertura parcial.
El feed de notificaciones y Web Push están implementados, aunque Web Push requiere claves
VAPID configuradas en el ambiente. El match probabilístico con porcentaje y memoria de
alias sigue pendiente. Las secciones siguientes conservan el requerimiento original de
2026-07-09; expresiones como «hoy no existe» describen esa fecha.

---

## 1. Qué existe hoy (base sobre la que se construye)

El WMS ya cubre el flujo físico completo de bodega, integrado a Defontana:

- **Pedidos → Picking → Packing → Despacho.** `OrderStatus` incluye `pending_picking`, `picking`, `picked`, `ready_to_dispatch`, etc. Las líneas de pedido (`OrderLineStatus`) pueden quedar `pending` o `missing`.
- **Picking con tareas y líneas.** Una `PickingTask` tiene líneas con estado `pending`, `picked`, `missing` o `partial`. El operario escanea antes de confirmar; puede marcar faltante con motivo; **un picking con líneas pendientes NO se cierra salvo que un supervisor autorice picking parcial** (`allow_partial`). Esto ya deja "pedidos parciales" registrados en el sistema — exactamente el caso del que habla el cliente.
- **Inventario con movimientos.** Toda entrada de stock genera un movimiento `RECEIPT` en `inventory_movements` y actualiza `inventory_balances`. Es decir, **el "ingreso de productos al stock" que hace el jefe ya es un evento capturable** por el sistema.
- **Productos.** Tienen `sku`, `name`, `description`, `brand`, `category` y códigos de barra. **Hoy el emparejamiento es exacto** (por SKU o código de barra); no existe ningún match difuso ni por probabilidad.
- **PWA móvil (modo operario)** optimizada para pistola/cámara, y **worker** que consume una cola de `sync_jobs` sobre Mongo.
- **No existe hoy** ninguna infraestructura de notificaciones/alertas al operario. Es lo que hay que crear.

---

## 2. Qué pide el cliente (traducción de la nota de voz)

La transcripción viene entrecortada, pero el mensaje es claro y contiene **dos funcionalidades distintas**:

**A) El problema del operario ocioso y dependiente del jefe.** El jefe estaba ingresando productos al stock mientras el operario ("el Niño") hacía otra cosa. Hay pedidos que quedaron **parciales** porque faltaban productos que estaban **pendientes de ingreso**. Cuando esos productos por fin llegan y el jefe los ingresa, el operario *podría* ir a terminar esos pedidos parciales — pero **hoy no lo hace solo**: depende de que el jefe le avise físicamente ("oye, completa esta orden porque esto ya llegó"). Si el jefe no está presente, no pasa nada y el operario queda ocioso. El cliente quiere que **el móvil le avise automáticamente**.

**B) El problema del descriptor que no calza.** A veces el descriptor con que se cotiza un producto (lo que ingresa "la Tami") no coincide con el descriptor real del inventario; el jefe los va modificando "a su descriptor real" cuando procesa el pedido. Entonces un producto pendiente no siempre matchea 1-a-1 con lo que hay en stock. El cliente quiere un **match con porcentaje de probabilidad**, "como el que tenía en Mercado Público": el sistema muestra candidatos ("100% de probabilidad de que este producto sea eugenol… otra marca con 80%") y **avisa que existen posibilidades de completar el pedido**, para que el operario vaya a buscar.

---

## 3. Requerimiento 1 — Alerta automática: recepción de stock → pickings parciales completables

### Historia de usuario
> Como operario de bodega, quiero recibir una alerta en el móvil cuando se ingresan al stock productos que estaban frenando pedidos parciales, para ir a completar esas órdenes sin depender de que el jefe me avise y sin quedar ocioso.

### Comportamiento esperado
1. Cuando se registra una **recepción/ingreso de stock** (movimiento `RECEIPT`), el sistema evalúa automáticamente qué **pickings/pedidos parciales o pendientes** estaban esperando exactamente esos productos.
2. Si el ingreso deja **stock suficiente** para completar una o más líneas pendientes/parciales, el sistema genera una **alerta** dirigida al operario (y opcionalmente al supervisor).
3. La alerta aparece en el **móvil (PWA)** como notificación/badge: *"Se ingresaron productos. Estas órdenes de picking ya pueden completarse: #1001, #1043…"*.
4. El operario abre la orden desde la alerta; el sistema confirma que **ahora hay stock disponible** ("está lista") y le permite ir a completar el picking parcial.

### Reglas de negocio
- La alerta se dispara solo cuando el ingreso **cierra la brecha** de al menos una línea pendiente/parcial (cantidad recibida ≥ cantidad faltante), o de forma parcial si se opta por avisar también por cierres parciales (decidir — ver §5).
- Debe respetar `tenant_id`, bodega y reservas (`quantity_reserved`): solo cuenta stock **realmente disponible** para esa orden.
- No debe duplicar alertas: si ya existe una alerta abierta para esa orden por el mismo producto, se actualiza en vez de crear otra.
- Se registra en auditoría (`audit_logs`) igual que las demás acciones críticas.
- Reutiliza el "picking parcial autorizado por supervisor" ya existente; esta feature **no cierra pickings sola**, solo avisa que ya se pueden completar.

### Impacto técnico (orientativo, sobre la arquitectura actual)
- **Backend**
  - Enganchar en `inventory_service` (flujo de recepción / `MovementType.RECEIPT`) un paso que, tras confirmar el ingreso, invoque un nuevo servicio `replenishment_alert_service`.
  - Nuevo servicio que consulte pickings/órdenes con líneas en `pending`/`partial`/`missing` que referencien el `product_id` recibido y compare faltante vs. disponible.
  - Nueva colección `notifications` (o `alerts`): `tenant_id`, `type` (`receipt_unblocks_order`), `target_user_id`/rol, `order_id`, `picking_task_id`, `product_ids`, `status` (`unread`/`read`/`resolved`), `created_at`.
  - Nuevos endpoints REST: `GET /api/v1/notifications` (con filtro no leídas), `POST /api/v1/notifications/{id}/read`. Opcional: emitir vía el `worker`/cola para no bloquear la recepción.
- **Frontend (PWA operario)**
  - Indicador/badge de alertas + pantalla de lista. Al tocar una alerta, navegar a la orden/picking correspondiente.
  - Poll periódico o push (según lo que ya soporte la PWA).

### Criterios de aceptación
- Dado un pedido parcial esperando el producto X, cuando se ingresa stock suficiente de X, entonces se crea una alerta visible en el móvil del operario en < 1 min.
- Si el stock ingresado no alcanza para ninguna línea pendiente, no se genera alerta.
- Abrir la alerta lleva a la orden y muestra que las líneas antes bloqueadas ya tienen stock disponible.
- No se generan alertas duplicadas para el mismo (orden, producto) mientras siga abierta.

---

## 4. Requerimiento 2 — Match probabilístico de productos ("estilo Mercado Público")

### Historia de usuario
> Como operario/jefe, quiero que cuando un producto pendiente no calce exactamente con el inventario, el sistema me sugiera productos candidatos con un porcentaje de probabilidad, para identificar rápido con qué ítem del stock puedo completar el pedido.

### Comportamiento esperado
1. Cuando una línea de pedido/picking no encuentra match exacto (por descriptor distinto al cotizado), el sistema calcula **candidatos** desde el catálogo/inventario y los ordena por **score de similitud** (ej.: "eugenol marca A — 100%", "eugenol marca B — 80%").
2. Se muestra la lista de candidatos con su porcentaje; el operario/jefe **elige** cuál corresponde (o descarta).
3. Idealmente se combina con el Req. 1: la alerta de recepción puede decir *"existen posibilidades de completar este pedido"* cuando hay candidatos con score sobre un umbral.

### Reglas de negocio
- El match es **sugerencia, no decisión automática**: siempre requiere confirmación humana antes de asociar un producto real a la línea.
- Umbrales configurables: p. ej. mostrar candidatos ≥ 60%; marcar "alta confianza" ≥ 90%.
- La similitud se calcula sobre campos relevantes: `name`/`description`/`brand`/`category` (y sinónimos del rubro dental, si se quiere afinar).
- Guardar las confirmaciones para **aprender**: cada vez que se confirma "descriptor cotizado X = producto real Y", se persiste como alias/mapeo para acelerar futuros matches (idealmente exactos la próxima vez).

### Impacto técnico (orientativo)
- **Backend**
  - Nuevo `product_matching_service` con una función `suggest_matches(texto_o_linea) -> [{product_id, score, reason}]`.
  - Enfoque incremental: empezar con similitud de texto (normalización + token/trigram + `rapidfuzz`) sobre nombre/descripción/marca; dejar la interfaz preparada para reemplazar por embeddings/semántica si hace falta.
  - Colección `product_aliases` (`tenant_id`, `alias_text`, `product_id`, `source`, `created_by`) para memorizar equivalencias confirmadas.
  - Endpoint `GET /api/v1/products/match?q=...` (o `POST` con la línea) que devuelve candidatos con score.
- **Frontend**
  - Componente de "sugerencias de match" con % y botón de confirmar/descartar, disponible en la resolución de líneas pendientes y en la vista de la orden.

### Criterios de aceptación
- Dada una línea con descriptor "eugenol" sin match exacto, el sistema devuelve candidatos ordenados por score con su porcentaje.
- El operario puede confirmar un candidato; la asociación queda registrada y la línea puede completarse.
- Una equivalencia confirmada se reutiliza automáticamente en pedidos futuros.
- Ningún producto se asocia a la línea sin confirmación humana.

---

## 5. Decisiones abiertas (a confirmar con el cliente antes de construir)

1. **Destinatario de la alerta:** ¿solo el operario asignado, cualquier operario disponible, o también el supervisor/jefe?
2. **Canal:** ¿basta con badge + lista dentro de la PWA (poll), o se requiere push real / sonido para que "no quede ocioso"?
3. **Cierres parciales:** si el ingreso alcanza para *parte* de la línea faltante, ¿avisar igual o solo cuando se puede completar del todo?
4. **Alcance del match:** ¿buscar candidatos en todo el catálogo o solo entre lo que tiene stock disponible? ¿Umbrales exactos (60/90%)?
5. **Aprendizaje:** ¿queremos ya la memoria de alias (`product_aliases`) en la v1 o dejarla para una segunda iteración?

---

## 6. Prompt de implementación (listo para usar)

> Copiar/pegar como instrucción para desarrollar sobre el repo `wms-insumedent` (FastAPI + Motor/MongoDB + React PWA).

```
Contexto: WMS multiempresa (backend FastAPI + Motor/MongoDB, frontend React/Vite PWA
con modo operario móvil, worker sobre cola sync_jobs en Mongo). El flujo Pedido →
Picking → Packing → Despacho ya existe. Las recepciones de stock generan un movimiento
MovementType.RECEIPT en inventory_movements y actualizan inventory_balances. Los pickings
pueden quedar parciales (líneas pending/partial/missing) y solo se cierran con autorización
de supervisor. Hoy el match de productos es exacto (SKU/código de barra) y NO existe
infraestructura de notificaciones.

Implementa dos funcionalidades:

FUNCIONALIDAD 1 — Alerta de recepción que desbloquea pickings parciales:
- Tras confirmar una recepción (RECEIPT) en inventory_service, evaluar qué órdenes/pickings
  con líneas pending/partial/missing esperaban ese product_id y ahora tienen stock disponible
  suficiente (considerando quantity_reserved y bodega/tenant).
- Crear una colección `notifications` y un servicio `replenishment_alert_service` que genere
  una alerta tipo `receipt_unblocks_order` dirigida al operario (y opcionalmente supervisor),
  con order_id, picking_task_id y product_ids. Evitar duplicados (actualizar la existente).
- Exponer endpoints GET /api/v1/notifications (no leídas) y POST /notifications/{id}/read.
  Registrar en audit_logs. No cerrar pickings automáticamente: solo avisar.
- En la PWA operario: badge + lista de alertas; al tocar una, navegar a la orden/picking.

FUNCIONALIDAD 2 — Match probabilístico de productos (estilo Mercado Público):
- Servicio `product_matching_service.suggest_matches(texto|línea) -> [{product_id, score, reason}]`
  usando similitud de texto (normalización + rapidfuzz sobre name/description/brand/category),
  con umbrales configurables (mostrar ≥60%, alta confianza ≥90%). Interfaz preparada para
  cambiar a embeddings más adelante.
- Colección `product_aliases` para memorizar equivalencias confirmadas (alias_text→product_id)
  y reutilizarlas como match exacto en el futuro.
- Endpoint GET /api/v1/products/match?q=... que devuelve candidatos ordenados por score.
- En la PWA: componente de sugerencias con % y confirmar/descartar en la resolución de líneas
  pendientes. El match es sugerencia; nada se asocia sin confirmación humana.
- Integrar con la Funcionalidad 1: si al recibir stock hay candidatos ≥ umbral para una línea
  sin match exacto, la alerta indica "existen posibilidades de completar este pedido".

Requisitos transversales: respetar tenant_id y roles existentes (picker/supervisor/…),
escribir tests de flujo (pytest, estilo test_flow.py) para: (a) recepción que genera alerta
y no duplica, (b) recepción insuficiente que no genera alerta, (c) suggest_matches ordena por
score y respeta umbral, (d) alias confirmado se reutiliza. No romper el flujo de picking/packing/
despacho actual.
```
