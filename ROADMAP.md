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
- **Flujo 2 — Recepción y ajustes → `Inventory/Insert`** *(tipos y motivos definidos y
  probados; solo falta el centro de negocio)*. Defontana respondió (2026-09-17) que **el tipo
  de documento, el motivo y el centro de negocio los define Insumedent**. Decisión A.1
  (2026-09-19), probada contra la API de pruebas creando y borrando un documento de cada caso:

  | Flujo | Documento | Motivo |
  |---|---|---|
  | Recepción | `PE` (Parte de Entrada, sugerencia de Defontana) | `COMPRA` |
  | Ajuste positivo | `XAJ_ENT_UN` | `ENTRADA` |
  | Ajuste negativo y merma | `XAJ_SAL_UNID` | `SALIDA` |

  El motivo de ajuste era un solo parámetro que, vacío, caía en `COMPRA`: una merma habría
  viajado como compra. Ahora hay uno por sentido. El envío sigue **apagado**
  (`DEFONTANA_INVENTORY_SYNC_ENABLED`) porque el **centro de negocio** va dentro de cada
  documento y está pendiente de confirmar por Insumedent (A.2); hoy se usa `EMPNEGVTAVTA000`,
  copiado de una guía real. No se puede consultar por API (Contabilidad no está contratada): hay
  que verlo en el ERP web, Configuración → Contabilidad → Centros de negocio.
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
- **Flujo 3 — Guía de despacho → `Order/DispatchOrder`** *(pendiente de valores)*. Falta el
  mapeo de `dispatchInfo` (tipo de bien `1` "Constituye una venta", tipo de despacho `1` "Por
  cuenta del cliente") y `originStorageInfo.motive`.
- **Reemplazo de productos en picking** *(decidido y construido del lado WMS: despachar sin la
  línea y guía aparte para lo pendiente — A.7)*. Insumedent eligió la alternativa (a): se
  despacha lo que hay y lo que falta sale después en otra guía. Un pedido **despachado** con
  cumplimiento parcial vuelve a aparecer en "Llegó stock · listos para completar" cuando hay
  stock; "Preparar pendiente" crea una tarea de picking **nueva** solo con lo que falta
  (`is_backorder`, `sequence` 2, 3…), que sigue a packing y a una segunda guía. Las cantidades
  del pedido son la suma de las tareas cerradas, y reabrir picking o packing sobre el pendiente
  solo toca esa tarea: la guía anterior y su inventario quedan intactos. Un pedido "despachado
  en parte" (queda algo empacado sin despachar) no se ofrece: primero se despacha eso. El lado
  del ERP sigue esperando el mapeo de `Order/DispatchOrder` (ver Flujo 3).
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
  `docs/entregables/Modelo-de-stock-con-Defontana.md`. Pendiente de construir:
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
     ya no hace falta aprobar las 282 una por una.
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
- **Búsqueda por texto en el servidor** para `/orders`, `/packing/tasks` e
  `/inventory/balances`: hoy solo aceptan `status`/`limit`/`offset`, así que el buscador de
  esas pantallas filtra las filas ya cargadas y lo dice explícitamente. `/erp-stock` sí
  busca en el servidor (acepta `q`), y ahí el buscador es real.
- **Buscador global y selector de bodega activa** en el header: necesitan endpoints que no
  existen.
- **Panel de rendimiento / tiempos del operario**: el backend no registra esos datos.
- **Métricas de stock mínimo y ocupación de ubicaciones**: no están en el modelo de datos.
- **Reestructurar Recepción y Ajuste en pasos**: depende de las definiciones del cliente que
  están abiertas en «Integración Defontana».

---

## Pendiente (funcional)

- **Endpoints reales de Defontana para crear producto / crear pedido.** La
  integración hoy sólo **lee** productos y pedidos desde Defontana; su API no
  expone (o no se ha confirmado) endpoints para **crear** un producto o un pedido.
  Por eso los jobs `create_product` y `create_order` responden OK en mock y lanzan
  `NotImplementedError` en modo real. Cuando se confirmen los endpoints reales, conectarlos en
  `DefontanaConnector.create_product` / `create_order`
  (`backend/app/integrations/defontana/client.py`).
  *Corrección 2026-09-20:* el flag `ERP_CREATE_ENABLED` (`frontend/src/config.ts`) **ya está en
  `true`**, así que las acciones "Nuevo producto / pedido" **sí se ven** en la UI. No es porque
  los endpoints estén resueltos, sino por la **operación stand-alone**: sin ERP del cual
  importar, el alta se hace a mano en el WMS. Lo que evita que eso toque a Defontana es
  `ERP_SYNC_ENABLED=false` en el backend, que hace que crear no encole ningún job. Al conectar
  Defontana de verdad hay que prender esa variable, y recién ahí el alta manual empieza a
  empujar al ERP.
  *(Actualización 2026-09: Pedidos sí expone `Order/SaveOrder` / `UpdateOrder`; crear productos
  es `Sale/SaveProduct`, del módulo Ventas, no contratado. La recepción → `Inventory/Insert`
  está probada en pruebas pero el payload del WMS aún no tiene el formato real: ver
  "Integración Defontana".)*

- **Nombre y logo del producto.** Pendiente de definir (lo verá el dueño). Hoy hay una
  marca provisional (cuadrado cian con la letra «S») en tres lugares: el bloque de marca
  de `Layout.tsx`, la tarjeta de `LoginPage.tsx` y el encabezado de `PublicBultoPage.tsx`
  (esta última la ve el cliente al escanear el QR del bulto). Cuando esté definido,
  reemplazar en esos tres y en el favicon.

---

## Hecho (referencia rápida)

- Catálogo dental real de INSUMEDENT en la demo (1251 productos con stock real, 17 categorías).
- Flujo completo **picking → packing → despacho** clickeable, operable sin pistola lectora.
- Escáner con **soporte móvil**: cámara para escanear + teclado en pantalla al tocar.
- **"Volver a escanear"** para corregir líneas en picking y packing.
- **Retomar** tareas en curso: filas clickeables en Picking/Packing y "Continuar picking" en Pedidos.
- **Impresión de etiquetas** de productos con código de barras EAN-13 (A4 o impresora térmica).
- **Etiqueta por bulto (1/N)** en packing: cliente, productos y cantidad por bulto.
- **Recepción de mercadería** (con ubicación → etiqueta → sync ERP real vía `Inventory/Insert`).
- **Alta de producto / pedido** (backend listo, con job de sync; UI oculta hasta endpoints reales).
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
