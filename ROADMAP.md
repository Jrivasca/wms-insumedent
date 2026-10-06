# Roadmap / Pendientes

Mejoras acordadas para más adelante. No bloquean la demo actual.

---

## Camino a SaaS (producto vendible multi-empresa)

Este WMS pasará a ser un **servicio SaaS** que se venderá a muchas empresas, cada
una con su propio espacio y creciendo en módulos a medida. La base ya ayuda: el
modelo de datos es **multi-tenant** (`tenant_id` en todo, JWT que lo lleva), está
**en contenedores** (portable, sin lock-in) y ya tiene auditoría y secretos cifrados.

**Decisiones tomadas:**
- **Nube:** DigitalOcean (o Hetzner para máximo ahorro) para cómputo.
- **Base de datos:** **MongoDB Atlas** (gestionado, backups, agnóstico de nube).
- **Arquitectura:** mantener el **monolito modular** (FastAPI + worker + React); NO microservicios todavía.
- **Multi-tenancy:** modelo **"pool"** (BD compartida + `tenant_id`); tier de BD dedicada como upsell enterprise más adelante.

### Prioridad 1 — Des-arriesgar datos y base SaaS
1. **Migrar Mongo → MongoDB Atlas** *(pendiente — siguiente paso)*. Crear clúster
   (M0 gratis para dev / M10 para prod), `mongodump` del droplet → `mongorestore`
   al clúster, cambiar `MONGODB_URI` en `.env`, redeploy, y permitir la IP del
   droplet (`137.184.137.130`) en el firewall del clúster. Activar backups automáticos.
2. ~~**Guardia central de aislamiento por tenant**~~ *(hecha, 2026-08-11)*:
   `backend/app/core/tenant_db.py` expone `tenant_db(tenant_id)`. Los servicios lo piden en vez
   de `get_database()` y trabajan con la misma API `db[Collections.X]`, pero cada filtro y cada
   documento escrito quedan acotados al tenant solos: olvidar el filtro ya no fuga datos, e
   intentar alcanzar otro tenant (en un filtro, un documento o un `$set` que reescriba el
   `tenant_id`) lanza `CrossTenantAccessError` en vez de cruzar el límite en silencio. Lo usan
   45 archivos —todos los servicios y los syncs de Defontana— y lo cubre
   `backend/app/tests/test_tenant_isolation.py`. Quedan fuera **a propósito**, porque operan
   entre tenants o antes de conocerlo, y así está documentado en el módulo: el poll global de
   jobs del worker (`sync_worker.claim_next_job`), `auth_service.login` /
   `deps.get_current_user` (pre-autenticación) y `seed.py` (bootstrap).
3. **Backups + restore probado** y export de datos por tenant.

### Prioridad 2 — Empaquetar como producto
4. **Entitlements / planes**: campo `plan` + `features` en el tenant; gating de
   módulos por flag (ya existe el patrón `ERP_CREATE_ENABLED`). Módulos vendibles:
   inventario, picking/packing, despacho, etiquetas, conectores ERP.
5. **Conectores ERP enchufables**: Defontana hoy; arquitectura para sumar otros ERP
   sin tocar el core (ver también pendiente de endpoints reales de Defontana abajo).
6. **Onboarding self-service**: registro → provisión automática del tenant → seed
   base. Separar un **"control plane"** (registro / admin / facturación) del app del tenant.
7. **Facturación: Stripe** (suscripción por empresa o por usuario; planes ↔ entitlements).
8. **Un cliente = un subdominio** (`empresa.tuwms.cl`) o dominio propio (Caddy ya
   soporta TLS automático on-demand).

### Prioridad 3 — Operación y confianza para vender
9. **Observabilidad**: Sentry (errores) + monitoreo de uptime + logs centralizados.
10. **Ambiente de staging** + CI/CD (ya hay GitHub Actions + tests; falta staging y
    deploy continuo).
11. **Seguridad / compliance**: rotación de secretos, política de datos (Ley 19.628
    CL), y SOC2 cuando se venda a enterprise.

### Cómo funcionará en la práctica (tenants, usuarios, admin, dominios)

**Creación de tenant + usuarios** (la base ya existe: `users` tienen `tenant_id` +
`role`, el JWT lleva el `tenant_id`, y el `seed` ya crea tenant + admin + datos base):
1. **Provisionar el tenant**: crear el registro (nombre, plan, estado) + su primer
   **usuario admin** + seed base (bodega, ubicaciones). Generalizar el `seed` en una
   función `create_tenant`.
2. El **admin del cliente** entra y crea/invita a su equipo (operarios, supervisores),
   cada uno con su rol; solo ven los datos de SU empresa.

**Dos niveles de admin (no confundir):**
- **Admin del cliente** (gestiona SUS usuarios/bodegas/config) → es **producto**;
  construir la UI "Equipo" cuando un cliente la necesite.
- **Admin de la plataforma** (crear/suspender empresas, plan/módulos, uso, cobro) →
  es el **control plane**, separado del app del tenant.

**Estrategia: a medida, no un módulo grande de entrada.**
- Primeros clientes (1–10): provisionar con **script/endpoint protegido** (el `seed`
  ya es casi eso); crear usuarios por script si hace falta.
- Después: UI de gestión de usuarios del cliente (producto).
- Cuando el volumen lo justifique: **control plane** real + onboarding self-service + Stripe.

**Dominios / subdominios:**
- **DNS comodín**: `*.midominio.app` → IP del servidor, configurado UNA vez; cubre
  todos los tenants (`acme.midominio.app`, etc.) sin crear un DNS por cliente.
- El subdominio **identifica** al tenant (el backend lee el `Host`), pero la
  **seguridad real** es el login + `tenant_id` en la base. Los usuarios se autentican
  normal; el subdominio solo da contexto/branding. TLS automático con Caddy.
- **Se puede partir SIN subdominios** (un solo `app.midominio.app`; el tenant sale del
  JWT). Agregar subdominios (branding) y **dominios propios del cliente** (CNAME →
  upsell) más adelante.

### Escalamiento (cuando toque)
- **Etapa 1 (1–20 clientes):** 1 droplet + Atlas + BD compartida. ~US$30–60/mes.
- **Etapa 2 (20–200):** backend con réplicas, Atlas con backups/réplica, Spaces/S3,
  Sentry, staging, Stripe + entitlements.
- **Etapa 3 (200+):** Kubernetes (DOKS/EKS), tier de BD dedicada para enterprise,
  multi-región, SSO, SOC2.

---

## Integración Defontana (en curso)

Contexto: APIs contratadas = **Pedidos, Inventario y Guías de Despacho** (Ventas no).
Soporte: canal Slack `integracion-insumedent` con Luis Lopez (Defontana). Detalle técnico y
hallazgos en `docs/entregables/Analisis-APIs-Defontana-a-contratar.md` (v3).

- **Flujo 1 — Extraer pedidos por despachar** *(implementado y confirmado por Defontana)*.
  `Order/List` + `Order/Get`, importa estados `E..`, ventana `DEFONTANA_ORDERS_WINDOW_DAYS`
  (90), reconcilia anulados/cerrados/despachados fuera del WMS. Respuestas de Luis
  (2026-09-15): el filtro `Status` acepta **un solo código por consulta** (se mantiene traer
  el rango y filtrar `E..` localmente); ciclo del pedido **P → AC → AF → EEX**, y puede pasar a
  `D..` si la guía se emite directo en el ERP (lo cubre la reconciliación); **un pedido solo
  se puede editar en estado P**; el ambiente de pruebas se atrasó por un problema interno y
  se actualiza el fin de semana. Pendiente sin respuesta: qué proceso usa hoy el usuario
  `INTEGRACION`.
- **Flujo 2 — Recepción y ajustes → `Inventory/Insert`** *(tipos, motivos y centro de negocio
  definidos y probados)*. Defontana respondió (2026-09-17) que **el tipo de documento, el motivo
  y el centro de negocio los define Insumedent**. Decisión A.1 (2026-09-19), probada contra la
  API de pruebas creando y borrando un documento de cada caso:

  | Flujo | Documento | Motivo |
  |---|---|---|
  | Recepción | `PE` (Parte de Entrada, sugerencia de Defontana) | `COMPRA` |
  | Ajuste positivo | `XAJ_ENT_UN` | `ENTRADA` |
  | Ajuste negativo y merma | `XAJ_SAL_UNID` | `SALIDA` |

  El motivo de ajuste era un solo parámetro que, vacío, caía en `COMPRA`: una merma habría
  viajado como compra. Ahora hay uno por sentido.
- **A.2 — Centro de negocio *(confirmado, 2026-09-21)*.** El valor es **`EMPNEGVTAVTA000`**
  (`DEFONTANA_BUSINESS_CENTER`). Se verificó en el ERP web de Insumedent en **Configuración →
  General → Centro de Negocios** (no en Contabilidad, como decía antes esta bitácora): el árbol
  es `EMP` → `EMPNEG` → `EMPNEGVTA` → **`EMPNEGVTAVTA`** (descripción VENTAS, imputable). La UI
  muestra el código recortado (`EMPNEGVTAVTA`), pero **la forma de cable lleva el nivel de hoja
  con relleno `000`**: un `Inventory/GetDocument` sobre una guía real devuelve
  `EMPNEGVTAVTA000`, y un `Inventory/Insert` de prueba con ese valor lo aceptó y lo guardó como
  `businessCenterId: EMPNEGVTAVTA000` / `businessName: VENTAS` (Parte de Entrada folio 884,
  creada y **borrada** el 2026-09-21; el folio va como entero al borrar). No se puede listar por
  API (`Accounting/*` responde "no tiene habilitada la funcionalidad": Contabilidad no
  contratada), pero sí se ve en el ERP web y se probó por escritura. **No hay que cambiar el
  valor.** El envío sigue **apagado** (`DEFONTANA_INVENTORY_SYNC_ENABLED`) hasta el corte, no por
  A.2 sino porque la bodega todavía no opera con el WMS.
- **Sincronizaciones automáticas** *(listas, apagadas por defecto)*. Un solo programador en el
  worker (`defontana_scheduler`), con la última corrida guardada por empresa en
  `scheduler_runs` (sobrevive reinicios):
  | Nivel | Qué | Cuándo | Flag |
  |---|---|---|---|
  | Transaccional | Recepción, ajuste y despacho → ERP | Al instante, cola `sync_jobs` con 5 reintentos (30 s → 8 min) | `ERP_SYNC_ENABLED` + `DEFONTANA_INVENTORY_SYNC_ENABLED` |
  | Frecuente | Pedidos por despachar | Cada `DEFONTANA_ORDERS_SYNC_INTERVAL_MINUTES` dentro de `DEFONTANA_ORDERS_SYNC_HOURS` (hora de `DEFONTANA_TIMEZONE`, días hábiles) | `DEFONTANA_ORDERS_SYNC_ENABLED` |
  | Diaria | Lotes + foto de stock del ERP | `DEFONTANA_STOCK_SYNC_AT` (03:30); si falla, reintenta a la hora siguiente | `DEFONTANA_STOCK_SYNC_ENABLED` |
  | Diaria | Conciliación WMS ← ERP: aplica sola lo chico, lo grande queda para revisión | `DEFONTANA_RECONCILE_AT` (04:30), con una foto de menos de 12 h | `DEFONTANA_RECONCILE_ENABLED` |
  | A demanda | Botones de la pantalla de Defontana e informe de stock | Cuando alguien lo pide | — |

  Si un envío al ERP agota sus reintentos, ahora avisa a los supervisores
  (notificación `sync_job_failed`, lleva a la Cola de Sincronización): antes quedaba
  descuadrado en silencio.
- **Flujo 3 — Guía de despacho → `Dispatch/Save`** *(B.1: **cerrado**. Estructura validada por
  Defontana, cuentas contables verificadas en QA, `priceList` resuelto (`"1"`, PR #36), **emisión real
  probada** (folio 3736, 2026-09-28) y **`erp_sync_enabled` ENCENDIDO en el droplet (2026-09-28)**: cada
  despacho confirmado ya emite guía real y consume folio de QA que no se borra)*. **El método cambió de
  `Order/DispatchOrder` a `Dispatch/Save`** (Luis, 2026-09-23: soporta lote/serie). El payload lo arma
  `DefontanaMapper.build_dispatch_save` (ver el detalle en la sección de lote/vencimiento, más
  arriba); el worker manda `Dispatch/Save` detrás de `erp_sync_enabled`. Valores confirmados que se
  reusan:
  - `dispatchInfo.assetsType` = **`1`** (tipo de bien "Constituye una venta"), `dispatchType` =
    **`1`** ("Por cuenta del cliente"), `transactionType` = **`1`** ("Venta del Giro"),
    `isTransferDispatch` = **false** — confirmados (spec de `Dispatch/Save`, Luis 2026-09-23/25).
  - `originStorage.motive` = **`VENTA`**; bodega de origen `BODEGACENTRAL` (= destino, no es traslado).
  - **Casing:** los campos van en **minúscula inicial** (camelCase), tal como el Swagger — confirmado
    por Luis (2026-09-25).
  - **`firstFeePaid`** (vencimiento): al contado = emisión; a crédito = emisión + los días del plazo
    del código de la condición (`CREDITO30` → 30). El ERP **no** lo calcula (Luis, 2026-09-25);
    lo resuelve el mapper (`_credit_days`).
  - **`businessCenter`** (`EMPNEGVTAVTA000`): es **por cuenta** — se envía solo si la cuenta lo tiene
    configurado; si no, no va. Se valida por cuenta con `Accounting/BusinessCenterPlan` (módulo
    Contabilidad, **no contratado**), así que la config por cuenta la confirma Insumedent con su ERP.
  - **`attachedDocuments`:** la **Nota de Pedido** (`documentTypeId 802`, folio = nº de pedido)
    **siempre va** (mueve el estado del pedido). Catálogo de códigos en
    `docs/entregables/Dispatch-Save-documentos-asociados.md`.
  - **Cuentas contables** (`DEFONTANA_DISPATCH_*_ACCOUNT`, ya cargadas como default): verificadas en
    vivo en el ERP QA el 2026-09-25 (`GDVELECT` → Definición Contable). La guía se contabiliza **solo**
    por el movimiento de inventario, así que las que importan son inventario de línea **`1110801001`**
    (MERCADERIAS) y de bodega **`4110101001`** (COSTOS DE VENTAS). Cliente (`1110401001`) y venta de
    línea (`1110801001`) son obligatorios en el payload pero no generan asiento propio en una guía.

  **El envío está detrás de `erp_sync_enabled`, ENCENDIDO en el droplet (2026-09-28).** O sea que
  confirmar un despacho **emite guía real en QA** (consume folio, no se borra). Con el flag apagado
  (como en local por defecto) el despacho queda **completo solo en el WMS** y no toca el ERP. Cubierto
  por tests (`test_flow` los dos caminos, `test_defontana_automation` la estructura del payload).
  - **Elegir lote al pickear** *(Parte 1, hecha 2026-09-24)*. `Dispatch/Save` manda lote/serie por
    línea, pero hasta ahora picking era **ciego al lote**: el FEFO solo elegía **ubicación**
    (`order_service._suggested_location`), no un lote puntual, y el staging no guardaba el
    vencimiento. Ahora, para un producto que maneja lotes, la app lista los lotes **pickeables
    ordenados FEFO** (`inventory_service.available_lots`, excluye ubicaciones no pickeables) y el
    operario **elige y confirma** el lote antes de escanear (obligatorio: sin lote el escaneo se
    rechaza). El pick descuenta **ese** lote y lo lleva a staging con su vencimiento, para que el
    lote viaje hasta la guía. Backend: `available_lots` + `scan`/`complete` con lote,
    `register_operational_move(lot_number, expiration_date)`, ruta
    `GET /picking/tasks/{id}/lines/{line_id}/lots`, `test_picking_lots.py`. Front:
    `PickingTaskPage` lista los lotes y bloquea confirmar sin elección (mirado renderizado el
    2026-09-24).
  - **El lote viaja hasta la guía** *(Parte 2, hecha 2026-09-24)*. Al cerrar el picking, el
    desglose de lote de lo pickeado queda en la línea del pedido (`order.lines[].picked_lots`,
    agrupado por lote+vencimiento, `order_service._picked_lots_by_line`). Al despachar, cada línea
    de la guía lleva sus lotes (`dispatch.lines[].lots`), asignados **FEFO** desde lo pickeado y
    restando lo que otras guías del mismo pedido ya despacharon (`dispatch_service._allocate_lots`;
    se acumula en `order.lines[].dispatched_lots` y se revierte al anular). Es el dato que poblará
    el `BatchInfo` de la guía. Cubierto por `test_picking_lots.py` (flujo picking→packing→despacho).
  - **Mapper de `Dispatch/Save`** *(hecho 2026-09-24)*. `DefontanaMapper.build_dispatch_save` arma
    el payload de la guía: la cabecera comercial (cliente, condición de pago, vendedor, moneda,
    local, lista, giro, comuna, región, precios) sale del **pedido original** (`raw_erp_data.order`
    = `Order/Get`); las líneas y su lote (`Details` + `BatchInfo`, `UseBatch`), del despacho del
    WMS (Parte 2). `DispatchInfo` confirmado (`assets/dispatch/transaction = 1`);
    `IsTransferDocument` configurable (default `true` = no viaja al SII). El worker
    (`_handle_dispatch_order`) ahora manda `Dispatch/Save` (connector `dispatch_save`), detrás del
    mismo candado `erp_sync_enabled` (**encendido en el droplet desde 2026-09-28**).
    `build_dispatch_order` (Order/DispatchOrder) queda superado pero se conserva. Cubierto por
    `test_defontana_automation`. **Estructura validada por Defontana (Luis, 2026-09-25):** casing
    (minúscula inicial), `attachedDocuments` (Nota de Pedido 802 obligatoria), `businessCenter` por
    cuenta, IVA en `saleTaxes`, `firstFeePaid` por condición de pago, `documentType` = `GDVELECT`,
    `motive` = `VENTA` — todo aplicado. **Cuentas cargadas y verificadas en QA**
    (`DEFONTANA_DISPATCH_*_ACCOUNT`, 2026-09-25). **Emisión real probada** (2026-09-28, folio 3736, con
    lote, `IsTransferDocument=true` → sin SII). **`priceList` resuelto:** NO es el
    `referenceNumberPricingID` (da "out of range"); es un código de `GetPriceList` (Ventas, no
    contratado), va por config `DEFONTANA_DISPATCH_PRICE_LIST` — Insumedent eligió `"1"` (LISTA BASE),
    que es el default (PR #36). **B.1 cerrado:** no queda nada por definir; con el flag encendido cada
    despacho confirmado en el droplet emite guía real (consume folio de QA, no se borra). Ejemplo en
    `docs/entregables/Dispatch-Save-*.{json,md}`.
  - **Corregir/actualizar lotes** *(Parte 3, opción A — hecha 2026-09-24)*. Cuando el lote del
    saldo está mal ingresado, el operario lo corrige **en picking** para liberar el despacho:
    "Actualizar lotes desde Defontana" refresca la foto de referencia (`erp_batches`,
    `product_sync.sync_batches`, no mueve stock) y muestra los lotes correctos; el operario
    re-etiqueta el saldo del lote malo por el correcto (`inventory_service.correct_balance_lot`).
    Es un **relabel que conserva la cantidad** —no un ajuste de cantidades— modelado como dos
    movimientos `lot_correction` net-zero auditados, así que no viaja al ERP (Defontana ya manda
    cantidades y lotes) y por eso lo hace el operario y no un supervisor. Rutas
    `GET .../erp-lots`, `POST .../correct-lot`, `POST /picking/sync-lots`; UI en
    `PickingTaskPage` ("¿El lote está mal? Corregir lote"). Cubierto por `test_picking_lots.py`
    y mirado renderizado + verificado en base el 2026-09-24 (LOTE-B→LOTE-CORRECTO-2027, cantidad
    conservada, dos movimientos auditados).
- **Reemplazo de productos en picking** *(decidido y construido del lado WMS: despachar sin la
  línea y guía aparte para lo pendiente — A.7)*. Insumedent eligió la alternativa (a): se
  despacha lo que hay y lo que falta sale después en otra guía. Un pedido **despachado** con
  cumplimiento parcial vuelve a aparecer en "Llegó stock · listos para completar" cuando hay
  stock; "Preparar pendiente" crea una tarea de picking **nueva** solo con lo que falta
  (`is_backorder`, `sequence` 2, 3…), que sigue a packing y a una segunda guía. Las cantidades
  del pedido son la suma de las tareas cerradas, y reabrir picking o packing sobre el pendiente
  solo toca esa tarea: la guía anterior y su inventario quedan intactos. Un pedido "despachado
  en parte" (queda algo empacado sin despachar) no se ofrece: primero se despacha eso. El lado
  del ERP usa `Dispatch/Save` (ver Flujo 3), aún detrás de `erp_sync_enabled`.
  **Defontana confirmó que un pedido solo se puede editar en estado P**; los que el WMS prepara
  ya están aprobados (`E..`), así que no se pueden modificar con `Order/UpdateOrder`. Hay que
  definir con Defontana y con Insumedent cómo se hace hoy un reemplazo en un pedido aprobado.
  Alternativas a evaluar: (a) despachar el pedido sin la línea faltante con
  `Order/DispatchOrder` y el sustituto en una guía aparte con `Dispatch/Save`; (b) cerrar el
  pedido (`M`) y crear uno nuevo con el sustituto (`Order/SaveOrder`), que vuelve a pasar por
  aprobación; (c) que ventas lo resuelva en el ERP y el WMS solo marque la línea faltante y
  avise. Lo de abajo es el diseño original, válido solo para la parte del WMS (marcar
  reemplazo, aprobación, cambio de línea en picking):
  Pedido del cliente: las cancelaciones son raras y casi siempre es un producto sin stock que
  se reemplaza por uno equivalente. Diseño propuesto:
  1. En picking, en una línea sin stock, el operario marca **"Reemplazar"** y escanea/busca el
     sustituto (el match por % del Requerimiento 2 puede sugerir candidatos con stock).
  2. El reemplazo queda **pendiente de aprobación** (supervisor / ventas): cambia lo que el
     cliente recibe y paga.
  3. Al aprobarse: la línea de picking pasa al producto nuevo (se recalcula la ubicación
     sugerida) y el pedido guarda el producto original para trazabilidad.
  4. Se encola `UpdateOrder` hacia Defontana; la guía de despacho solo se emite después de que
     Defontana confirme la actualización (la guía sale de las líneas del pedido).

  El paso 4 (`UpdateOrder`) queda descartado para pedidos aprobados; el tramo hacia Defontana
  depende de la alternativa que se elija.
- **Lotes desde Inventario** *(hecho)*: "Sync lotes" usa `Inventory/GetBatchesInfo` (módulo
  contratado; funciona en producción). **Solo trae los artículos que manejan lotes** (536 de
  3.359 en pruebas, aunque `totalItems` diga 3.359): los crea/actualiza, desactiva los inactivos
  existentes, no toca códigos de barra/marca/familia y guarda los lotes con vencimiento en
  `erp_batches` como referencia. Ya no se usa ningún endpoint de Ventas.
- **Catálogo completo de productos** *(sin API disponible)*: con lo contratado no hay un
  endpoint con el maestro completo. `Inventory/GetFutureStockInfo` trae los 3.359 códigos con
  descripción y stock, pero sin unidad, estado activo ni uso de lotes. **El catálogo sigue por el
  importador de Excel** (decisión A.8): no se crean productos automáticamente. Para revisarlo
  contra un Excel actualizado se entregó la lista de los que están en Defontana y no en el WMS
  (`docs/entregables/Productos-Defontana-no-en-WMS-2026-09-19.csv`): 181, **ninguno con stock
  hoy**, así que todo lo que existe físicamente ya está en el catálogo. Pero **tres tienen
  mercadería por recibir**: `102152` CARISTOP 5000 PASTA (720), `DNITTRESM` y `DNITTRESS`
  NITRILO TRESOR AZUL M y S (500 cada uno). Conviene agregarlos al Excel antes de que lleguen:
  sin producto en el catálogo no se pueden recibir en el WMS y la conciliación los deja
  bloqueados. La lista cubre los productos
  con desglose por bodega en la foto de stock; los que Defontana informa sin ninguna bodega (unos
  880, sin existencias) no se guardan y harían falta otra lectura para listarlos.
- **Informe "Stock ERP vs WMS"** *(hecho, informativo)*: "Traer stock de Defontana"
  (`Inventory/GetFutureStockInfo`: actual, reservado, por recibir) guarda una foto en
  `erp_stock`; Inventario → Stock ERP vs WMS la cruza con los saldos del WMS por SKU y bodega
  (vía `erp_storage_code`).
- **Modelo de stock decidido (2026-09-15): manda Defontana; el WMS ubica.** Ver
  `docs/entregables/Modelo-de-stock-con-Defontana.md`. Estado de implementación:
  1. **Conciliación WMS ← Defontana** *(hecha y en marcha)*. Decisiones A.3–A.5:
     diaria de madrugada (04:30, después de la foto de stock) y también manual desde Stock ERP
     vs WMS; lo que falta en el WMS se suma con los lotes del ERP en **`SIN-UBICAR`** (tipo
     recepción, no pickeable) hasta que bodega lo ubique; lo que sobra se descuenta por FEFO.
     Cada ajuste deja un movimiento auditable "Conciliación con ERP" y **no viaja a Defontana**.
     Las diferencias de más de 20 unidades (`DEFONTANA_RECONCILE_REVIEW_UNITS`) quedan para
     **revisión humana**: un supervisor las aprueba —en bloque o marcando filas— y la corrida
     diaria avisa si quedaron. **Primera corrida hecha a mano el 2026-09-19** (con respaldo
     validado antes): de 1.003 diferencias se aplicaron las 721 chicas (+2.374 / −1.915 unidades,
     749 movimientos, 0 errores, 0 envíos al ERP). Quedan **282 para revisión**, que concentran
     más del 95 % del volumen (+80.884 / −58.579 unidades). La corrida diaria quedó encendida en
     el ambiente local (`DEFONTANA_RECONCILE_ENABLED=true` en `.env`; en el código sigue apagada
     por defecto).
     **Aprobación en bloque** *(hecha, 2026-09-21)*: en Stock ERP vs WMS, «Aprobar N para
     revisión» aplica en bloque todas las que esperan revisión (sin tocar las chicas), y los
     checkboxes por fila permiten aprobar solo un subconjunto elegido («Aprobar seleccionadas»).
     El servicio lo hace con `apply(only_review=True[, keys=…])` y cada ajuste queda igual de
     auditado; la aprobación individual fila por fila sigue disponible. Esto destraba el corte:
     ya no hace falta aprobar una por una las 282 filas registradas el 2026-09-19; el
     pendiente real debe comprobarse con una vista previa nueva antes del corte.
  1bis. **Ubicar stock** *(hecho)*: la conciliación deja lo nuevo en `SIN-UBICAR`, que **no es
     pickeable**, así que hace falta guardarlo en su estante. `POST /inventory/putaway` mueve un
     saldo **exacto** (pantalla `/inventory/ubicar`, pensada para móvil y lector): como el saldo
     llega identificado, conserva lote, serie y vencimiento y no puede mover el equivocado. Antes
     esto se hacía con la transferencia, que no dejaba elegir lote y **perdía el vencimiento** en
     el destino (ese stock se caía del FEFO); la transferencia ahora también lo conserva.
     Además, la conciliación **ya no descuenta de STAGING/PACKING/DISPATCH**: esa mercadería está
     en la mano de un operario para un pedido. Lo que no se puede descontar del resto queda
     explicado en la fila y pasa por aprobación humana. Y la consulta de saldos busca **en el
     servidor** (SKU, nombre, código de barras, lote o serie) sobre todos los saldos, con orden
     fijo y escondiendo las filas en cero.

  1ter. **Vencimientos y puesta en marcha** *(hecho)*: `GET /inventory/expiring` y la pantalla
     **Vencimientos** (`/inventory/vencimientos`) muestran lo vencido y lo que vence dentro de
     180 días, en orden FEFO, con resumen por tramo (vencidos, ≤30 d, 31–90 d, 91–180 d) y
     filtros de bodega, ubicación y texto. Es independiente del aviso automático, que sigue
     avisando a 30 días y una sola vez por lote. El procedimiento del corte a producción está
     en `docs/entregables/Puesta-en-marcha-primera-vez.md`.

  2. ~~Push de ajustes y mermas~~ *(hecho)*: el ajuste viaja a `Inventory/Insert` como documento
     de entrada o salida (`XAJ_ENT_UN` / `XAJ_SAL_UNID`, configurables). El WMS no tiene
     transferencia entre bodegas, y la de ubicaciones no cambia el total: no se envía.
  3. **Lotes del ERP en la operación** (elegir lote conocido con su vencimiento al recibir/ubicar).
  4. ~~Ubicar stock recibido en Defontana~~ *(hecho)*: ver "Ubicar stock" más abajo.

  Las preguntas abiertas del documento quedaron respondidas (2026-09-19): se concilia a diario de
  madrugada y a demanda; las diferencias grandes van a revisión humana. Sigue abierta solo si
  compras registra recepciones directamente en Defontana (A.6); si ocurre, esas unidades
  aparecerán solas en `SIN-UBICAR` con la conciliación, así que el flujo ya lo cubre.
- **Bodegas** *(hecho)*: se administran **solo en el WMS**; se eliminó la sincronización de
  bodegas desde Defontana (botón, endpoint, job y conector).

---

## Rediseño de la interfaz (hecho, rama `feat/rediseno-ui`)

Dirección visual «control operacional de alta señal»: navegación grafito, cian como color
de interacción, fondo gris muy claro, superficies blancas y color con significado (ámbar =
advertencia, rojo = error, verde = correcto). Los códigos (SKU, ubicaciones, folios) van en
monoespaciada. Los tokens están en `frontend/tailwind.config.js` y las clases de componente
en `frontend/src/index.css`; los estados se traducen en `frontend/src/lib/status.ts` **sin
cambiar los valores internos** que viajan al backend.

Cubre las 26 pantallas: navegación agrupada (Mis tareas / Control / Operaciones /
Administración) con cajón y barra inferior en móvil, resumen ordenado por urgencia, listas
con tabla en escritorio y tarjetas en móvil, `LocationCombobox` con búsqueda en los
formularios de inventario, confirmaciones que explican la consecuencia en lugar de
`window.confirm`, y panel oscuro para la línea actual en picking y packing.

**Verificación:** `npx tsc --noEmit` en 0 después de cada tanda (12 commits). **Solo se
vieron renderizadas la pantalla de login y el resumen**; el resto compila y respeta los
contratos de datos, pero no se ha mirado en pantalla.

**Decisiones tomadas a propósito:**
- El marcado de las **etiquetas impresas** (50×30 mm, saltos de página, QR de 260 px) no se
  tocó: está calibrado para papel e impresora térmica y no se puede verificar sin imprimir.
- La **grilla del importador de PDF** no tiene variante de tarjetas en móvil: es una grilla
  de edición ancha que usa un supervisor en escritorio.

**Pendiente, y por qué:**
- **Búsqueda por texto en el servidor** para `/orders` y `/packing/tasks`: sus buscadores
  filtran las filas ya cargadas. `/inventory/balances` ya acepta `q` y busca en el servidor
  sobre todos los saldos, igual que `/erp-stock`.
- **Buscador global y selector de bodega activa** en el header: necesitan endpoints que no
  existen.
- **Panel de rendimiento / tiempos del operario**: el backend no registra esos datos.
- **Métricas de stock mínimo y ocupación de ubicaciones**: no están en el modelo de datos.
- **Reestructurar Recepción y Ajuste en pasos**: depende de las definiciones del cliente que
  están abiertas en «Integración Defontana».

---

## Pendiente (funcional)

- **Etiquetas en Zebra ZD220, 3 columnas × 30 × 10 mm** *(construido 2026-10-01, sin probar
  en la impresora)*. Perfil nuevo en Etiquetas: medidas editables (ancho del papel 95 mm
  provisional; márgenes y separaciones **sin medir**), filas de 3 con huecos en la última,
  cantidad por producto, total de etiquetas y filas, prueba de alineación y descarga en ZPL
  (`lib/labelRoll.ts`, `components/LabelRollSheet.tsx`). Validado a PDF y rasterizado a
  203 dpi; **falta**: medir márgenes/separaciones, imprimir la prueba de alineación, el avance
  de fila y la lectura con la pistola. Guía y limitaciones en `docs/etiquetas-zebra-zd220.md`.
  **Desplegado en el droplet el 2026-10-01** (`198c061`, PR #45; respaldo
  `/root/wms-backups/wms-2026-10-01-1505.*`) para la prueba física.

- **Match probabilístico de productos:** el aviso de reposición por producto exacto ya funciona,
  pero siguen pendientes las sugerencias de sustitutos con porcentaje y la memoria de alias
  confirmados que pide `docs/levantamiento-alertas-recepcion-y-match.md`.
- **Cierre parcial de picking por rol:** hoy `allow_partial` confirma el cierre con faltantes
  sin comprobar rol supervisor; decidir si se restringe y ajustar backend y UI si corresponde.

- **QA funcional 2026-09-29: PRs #38–#41 mergeados a `main` el 2026-09-30.** El dueño corrió la QA
  de interfaz en Claude-in-Chrome contra DEV y entregó el handoff con 7 hallazgos ALTA,
  11 MEDIA y ~20 BAJA. Se corrigieron **todos**, en tres PRs (más el #38 de mensajes en español y
  transferencia); **desplegados en el droplet el 2026-09-30** (`2091c99`, respaldo
  `/root/wms-backups/wms-2026-09-30-1531.*`):
  - **PR #39 — ALTA (A1–A7).** Validación de referencias en los movimientos de inventario
    (un `product_id` inexistente creaba saldos fantasma), cantidades enteras, motivo de
    ajuste con *strip*, vencimiento pasado, edición de pedido que ya no borra líneas en
    silencio, y **confirmación + idempotencia en el despacho** (con `erp_sync_enabled`
    encendido un doble clic emitía dos guías reales, cada una con su folio).
  - **PR #40 — MEDIA (M2–M11).** Packing cerrado deja de ser editable y con diferencias
    queda en «Completado con diferencias»; códigos de ubicación en los movimientos;
    Pedidos y Picking dejan de contradecirse; buscador que antepone el SKU exacto; lotes
    vencidos no pickeables; el botón de cámara ya no desborda en móvil.
  - **PR #41 — BAJA.** Textos unificados en **usted**, traducciones (`internal`,
    `erp_storage`, estado de Defontana), stepper topado, filtro de estado en Packing.

  **Pendiente de decidir / hacer:**
  - **Ninguna pantalla se verificó a ojo**: la extensión del navegador no acepta
    `localhost`/`127.0.0.1` en la máquina Linux. Conviene mirar sobre todo el PR #41.
  - **DEV limpio (2026-09-30)**: `app/maintenance/limpiar_movimientos_huerfanos.py --apply`
    borró en el droplet los 8 movimientos y los 2 saldos del `product_id` inexistente
    (`000000000000000000000000`); no tenían jobs de sincronización asociados. Respaldo previo
    en `/root/wms-backups/wms-2026-09-30-1538-pre-limpieza.dump`.
  - **El lote viaja también en packing y despacho (2026-10-06).** El picking dejaba cada unidad en
    STAGING con su lote, pero el packing (STAGING→PACKING) y el despacho (PACKING→salida) movían
    **sin lote**: quedaba +q en la fila con lote y −q en la sin lote (los negativos de STAGING del
    2026-10-05). Ahora el packing reparte lo empacado FEFO entre los lotes que pickeó su tarea de
    picking de origen (`picking_task_id`), y el despacho mueve según los lotes de la guía
    (`lines[].lots`); lo que no tenga lote sale sin lote. Reabrir/anular revierte con el mismo lote.
  - **Catálogo: importación del 2026-10-05 revisada.** El dueño importó el export de artículos de
    Defontana (1428 filas): 0 creados, 1428 «actualizados», pero comparado contra el respaldo previo
    solo cambiaron 7 campos (5 nombres, 1 categoría, 1 precio): no pisó datos buenos con vacíos.
    **Bug corregido:** en modo `read_only` openpyxl no deshace los escapes de OOXML y un tabulador
    del nombre quedaba como el texto `_x0009_` (14 productos). Ahora se aplica `unescape`; volver a
    importar el mismo Excel limpia los nombres. Los «181 productos de Defontana que faltaban»
    quedaron en 25, todos sin stock: ya no bloquean.
    **Códigos de barras: son del WMS** (EAN-13 internos; Defontana no los entrega, confirmado por
    el dueño). Solo se generaban con el «Informe de Artículos»: el Excel genérico, el alta manual y
    la sincronización dejaron **126 productos sin código** (124 con stock en Defontana). Ahora todo
    camino de alta llama a `ensure_internal_barcode` (si el interno choca con otro producto usa una
    variante, en vez de dejarlo sin código) y `app/maintenance/generar_codigos_internos.py`
    completa los que falten (dry-run por defecto).
    **Desplegado el 2026-10-05** (`48ba29e`, PR #55; respaldo `/root/wms-backups/wms-2026-10-05-1728.*`)
    y mantención aplicada: 126 códigos generados, 3493 productos con código, 0 repetidos.
  - **Fecha, cotización, vendedor y observaciones del pedido + paginación de 10 (2026-10-05, pedido
    del dueño).** De `Order/Get`: fecha = `creationDate` (`order_date`); cotización del ERP =
    `referenceNumberPricingID` (`quotation_number`; vacía en 4 de 35); vendedor = `sellerID`
    (`seller_code`: solo el código, el nombre es del módulo Ventas, no contratado); observaciones
    = el comentario (`observations`; en compras públicas trae el código de Mercado Público de lo
    cotizado, "…-COT26"). El dueño quiere ver ambas referencias. Los pedidos ya sincronizados los
    derivan del dato crudo. La grilla muestra solo la fecha; el resto va en el detalle del pedido
    (observaciones completas), la cabecera de picking/packing (`order_info`) y Despachos. Pedidos
    pagina de a 10 (selector 10/25/50). Abrir un pedido lo marca leído solo desde Pedidos
    (`?leido=true`).
    **Desplegado en el droplet el 2026-10-05** (`f55e709`, PR #54; respaldo
    `/root/wms-backups/wms-2026-10-05-1518.*`): 31 de 35 pedidos con cotización.
  - **Reinicio semanal de QA que también revierte el stock (2026-10-05).** Desde el 2026-09-28 un
    cron del droplet (solo en el servidor, fuera del repo) borraba los lunes pedidos, tareas y
    despachos y re-sincronizaba, **sin tocar el inventario**: lo movido por las pruebas quedaba en
    STAGING/PACKING sin pedido, con saldos negativos (el 2026-10-05: 19 u en STAGING, 7 en
    PACKING, 5 negativos). Además corrió a las 05:00 de Chile (`CRON_TZ` ignorado). Ahora
    `app/maintenance/reiniciar_qa.py`: (1) revierte con movimientos auditables (mismo lote) los
    de picking/packing/despacho **solo si no deja negativos** — el 2026-10-05 había correcciones
    manuales del 28/09 y revertir daba −18 en DISPATCH; (2) **vacía las ubicaciones operativas**
    mirando el saldo actual: cuadra los pares del bug de lote, devuelve lo positivo al origen del
    pick y repone lo negativo desde ahí. Script versionado en `deploy/qa/`, filtra la hora de
    Chile. El movimiento de packing sin lote (origen de los pares) se corrigió aparte (2026-10-06).
  - **Pedidos nuevos destacados, "no leídos" (2026-10-05, pedido del dueño).** Por usuario, como el
    correo: un pedido queda con punto azul y en negrita hasta que cada usuario lo abre
    (`orders.seen_by`, no sale en la API; la lista expone `unread` y `unread_total`). Los que
    llegan de Defontana quedan no leídos para todos; el que se crea a mano no le aparece como
    nuevo a quien lo creó. En Pedidos: contador «N sin leer», filtro «Solo no leídos» y
    «Marcar todos como leídos» (`POST /orders/mark-all-read`).
  - **Folio de la guía y reintentos (2026-10-02, folio 3737 en DEV).** Defontana rechazó una
    guía por falta de saldo (IVOCLAR017); se cargó el stock y se reintentó: la guía **salió**
    (3737), pero el WMS no leyó el folio (`Dispatch/Save` responde `firstFolio`; se buscaba
    `Folio`), el despacho quedó sin número y la cola siguió mostrando el error. Un segundo
    reintento la reenvió y "ya fue ingresado" quedó como fallo. Ahora: el folio se guarda como
    número de guía (`erp_folio`; no pisa una guía escrita a mano), "ya fue ingresado … Folio: N"
    cuenta como la misma guía (éxito), no se puede reintentar un envío exitoso (409) y la Cola
    de Sincronización se refresca sola mientras hay envíos en curso.
    **Desplegado en el droplet el 2026-10-02** (`0e4f8bb`, PR #50; respaldo
    `/root/wms-backups/wms-2026-10-02-2230.*`).
  - **Picking contra el stock real + alertas de quiebre (2026-10-02, observaciones del dueño).**
    Antes el escaneo no validaba stock (salvo lotes, y solo contra la propia tarea) y el cierre
    movía con `allow_negative`: se podía escanear de más y dos pedidos tomaban las mismas
    unidades, dejando saldos negativos en silencio. Ahora lo escaneado en un picking abierto
    queda **tomado** (reserva derivada de los escaneos, `services/picking_stock.py`, sin
    `quantity_reserved`): el escaneo se rechaza si no cabe en lo disponible de la ubicación/lote,
    dice dónde hay (o que está en recepción sin ubicar) y, en productos sin lote, cambia la
    ubicación sugerida a la que tiene stock. Sin stock, el pedido avanza con el cierre parcial.
    Notificación nueva **`stock_shortage`** (admin, supervisor, ventas): al generar el picking si
    el stock libre no alcanza, y al cerrarlo incompleto; lleva al pedido (`/orders?pedido=`).
    Pendiente conocido: dos escaneos *simultáneos* de la última unidad podrían pasar ambos (no
    hay bloqueo atómico); el cierre sigue con `allow_negative` como red de seguridad.
    **#48 y #49 desplegados en el droplet el 2026-10-02** (`ac26eff`; respaldo
    `/root/wms-backups/wms-2026-10-02-2201.*`).
  - **Pedidos en móvil (2026-10-02).** En el iPhone, tocar un pedido «no hacía nada»: el
    detalle se abría **debajo de toda la lista** (grilla de una columna), fuera de la vista.
    Ahora en pantallas angostas el detalle reemplaza a la lista, sube al inicio y trae
    «Volver a pedidos». En escritorio sigue lado a lado.
    **Desplegado en el droplet el 2026-10-02** (`8b1de2f`, PR #47; respaldo
    `/root/wms-backups/wms-2026-10-02-2035.*`).
  - **«Bulto 1» se crea solo (2026-10-01).** Antes había que crear el primer bulto a mano
    para poder escanear. Ahora lo crea `start_task`, y el primer escaneo si la tarea no tiene
    ninguno (tareas iniciadas antes del cambio); queda seleccionado. «Otro bulto» abre el 2.º
    en adelante; con varios bultos, escanear sin elegir uno se sigue rechazando.
    **Desplegado en el droplet el 2026-10-01** (`6f2cac1`, PR #46; respaldo
    `/root/wms-backups/wms-2026-10-01-1652.*`).
  - **Decidido (2026-10-01): un packing con faltantes queda pendiente.** «Finalizar packing»
    con faltantes respecto a lo pickeado deja la tarea «Con observaciones» **para todos**,
    también supervisor y admin (antes ellos la cerraban en el acto con el mismo botón). Cerrarla
    igual es un botón aparte, **«Cerrar con faltantes»**, solo de supervisor o administrador
    (`force_close` en `POST /packing/tasks/{id}/complete`; un operario recibe 403). Queda
    «Completado con diferencias» con `approved_by` y `force_close` en la auditoría. Cubierto por
    `test_packing_cierre.py`. **Desplegado en el droplet el 2026-10-01** (`c270100`, PR #44;
    respaldo `/root/wms-backups/wms-2026-10-01-1351.*`).
  - **Escaneo en el celular (2026-10-02, observaciones del dueño).** La «cantidad por escaneo»
    ahora también se escribe (solo dígitos; picking la topa en lo que falta), en picking y
    packing (`components/QuantityStepper.tsx`). La cámara usa el lector nativo del navegador
    (`BarcodeDetector`, Chrome en Android) con enfoque continuo: en un Android de gama básica
    ZXing en JavaScript tardaba demasiado. Safari (iPhone) no lo trae y sigue con ZXing, ahora
    con 100 ms entre intentos (antes 500). Probado el respaldo ZXing con cámara falsa; **el
    lector nativo solo se puede probar en un Android real**.
  - **No son defectos, aunque la QA los marcó:** "Reservado 0" en pedidos listos para
    despacho (el WMS nunca usa `quantity_reserved`: compromete stock moviéndolo de
    ubicación, que es el diseño) y el SKU duplicado (ya respondía 409 en español).

- **Altas manuales y escritura al ERP.** `ERP_CREATE_ENABLED=true` muestra «Nuevo producto» y
  «Nuevo pedido» para la operación local. Con `ERP_SYNC_ENABLED=false` se guardan en el WMS sin
  encolar un envío. `DefontanaConnector.create_product` y `create_order` siguen lanzando
  `NotImplementedError` en modo real; encender `ERP_SYNC_ENABLED` también habilitaría esos jobs.
  Crear producto en Defontana requiere `Sale/SaveProduct` (Ventas no contratado). Para pedidos
  existen `Order/SaveOrder` / `UpdateOrder`, pero aún no están conectados al flujo de alta y un
  pedido aprobado solo se puede editar en estado P. Resolver estos caminos antes de habilitar
  la escritura general al ERP. La recepción y los ajustes usan `Inventory/Insert` por `POST`,
  con tipos, motivos y centro de negocio confirmados (ver «Integración Defontana»).

- **Nombre y logo del producto.** Pendiente de definir (lo verá el dueño). Hoy hay una
  marca provisional (cuadrado cian con la letra «S») en tres lugares: el bloque de marca
  de `Layout.tsx`, la tarjeta de `LoginPage.tsx` y el encabezado de `PublicBultoPage.tsx`
  (esta última la ve el cliente al escanear el QR del bulto). Cuando esté definido,
  reemplazar en esos tres y en el favicon.

---

## Hecho (referencia rápida)

- **QA funcional de backend (2026-09-29)**: se tradujeron al español ~40 mensajes de error que
  aún salían en inglés (picking/packing, login, inventario, pedidos, usuarios, productos, sync);
  y la **transferencia rechaza origen == destino** (antes "pasaba" registrando dos movimientos
  espurios). Suite verde (199 tests). *Duda resuelta el 2026-10-01:* el packing incompleto
  queda pendiente y solo supervisor/admin lo cierra con «Cerrar con faltantes».
- Catálogo dental real de INSUMEDENT en la demo (1251 productos con stock real, 17 categorías).
- Flujo completo **picking → packing → despacho** clickeable, operable sin pistola lectora.
- Escáner con **soporte móvil**: cámara para escanear + teclado en pantalla al tocar.
- **"Volver a escanear"** para corregir líneas en picking y packing.
- **Retomar** tareas en curso: filas clickeables en Picking/Packing y "Continuar picking" en Pedidos.
- **Impresión de etiquetas** de productos con código de barras EAN-13 (A4 o impresora térmica).
- **Etiqueta por bulto (1/N)** en packing: cliente, productos y cantidad por bulto.
- **Recepción de mercadería** (con ubicación y etiqueta; envío a `Inventory/Insert` implementado,
  pero apagado hasta el corte de bodega).
- **Alta local de producto / pedido** (UI visible; envío real de esas altas al ERP pendiente).
- **Paginación** de listados (productos, saldos, movimientos).
- **Submenú Inventario** (Saldos / Recepción / Transferencia / Ajuste) con selector de producto.
- **Transportista** como lista desplegable (Bluexpress / NewTrans / Otro).
- **Rediseño completo de la interfaz** (ver sección propia): sistema visual, navegación
  agrupada con barra inferior en móvil, estados en español, tablas con variante de tarjetas.
- **Selector de ubicación con búsqueda** (`LocationCombobox`), acotado a la bodega elegida:
  antes los formularios de recepción, transferencia y ajuste ofrecían ubicaciones de
  cualquier bodega.
- **Mensajes de error entendibles**: se distingue el error que explicó el servidor, el que no
  explicó (mensaje por código) y el servidor que no contestó; los detalles de validación de
  FastAPI (arreglo `{loc, msg}`) se arman como «campo: mensaje».
- **Confirmaciones explicadas** al anular una guía, retroceder una etapa, cancelar un envío al
  ERP o descartar un pedido importado (antes eran `window.confirm` o un clic directo).
- **Estados de picking/packing más entendibles** (2026-09-21): cerrar un picking con faltantes
  ya no pasa en silencio por el botón verde —se vuelve ámbar «Completar picking (parcial)», dice
  «Faltan N unidades…» y abre una confirmación con la consecuencia—; el packing avisa antes de
  finalizar la diferencia contra lo pickeado, con el texto según rol (supervisor aprueba a su
  nombre; operario deja la tarea «Con observaciones»), y el 409 «observed» se explica en vez del
  genérico «líneas pendientes»; el listado de Pedidos muestra «Parcial · faltan N u» en vez de
  «Parcial» pelado. Los tres «incompletos» (pedido parcial, picking con diferencias, packing
  observado) están mapeados en la referencia visual del ciclo de vida del pedido.
  **Decisión abierta:** el cierre parcial de picking hoy lo confirma cualquiera (no hay candado
  por rol); definir si debe exigir un supervisor —sería un cambio chico de backend.
