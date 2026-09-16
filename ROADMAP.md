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
2. **Guardia central de aislamiento por tenant**: una capa de acceso a datos que
   SIEMPRE inyecte `tenant_id`, para que ninguna query pueda fugar datos entre empresas.
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
- **Flujo 2 — Recepción → `Inventory/Insert`** *(estructura probada en pruebas; faltan
  definiciones)*. Funcionó con motivo `COMPRA` y centro de negocio `EMPNEGVTAVTA000`. Pendiente
  confirmar tipo de documento (`PE` / `MOV001` / `XAJ_ENT_UN`, impacto contable), motivo,
  centro de negocio y si va el RUT del proveedor. El WMS ya arma el payload real
  (`DefontanaMapper.build_inventory_entry`, con lotes y vencimiento; probado en pruebas con
  precio 0), pero el envío está **apagado** hasta confirmar valores:
  `DEFONTANA_RECEPTION_SYNC_ENABLED` + `DEFONTANA_RECEPTION_DOCUMENT_TYPE` /
  `_REASON_ID` / `DEFONTANA_BUSINESS_CENTER` / `_CENTRALIZABLE`.
- **Sincronizaciones automáticas** *(listas, apagadas por defecto)*. Un solo programador en el
  worker (`defontana_scheduler`), con la última corrida guardada por empresa en
  `scheduler_runs` (sobrevive reinicios):
  | Nivel | Qué | Cuándo | Flag |
  |---|---|---|---|
  | Transaccional | Recepción, ajuste y despacho → ERP | Al instante, cola `sync_jobs` con 5 reintentos (30 s → 8 min) | `ERP_SYNC_ENABLED` + `DEFONTANA_INVENTORY_SYNC_ENABLED` |
  | Frecuente | Pedidos por despachar | Cada `DEFONTANA_ORDERS_SYNC_INTERVAL_MINUTES` dentro de `DEFONTANA_ORDERS_SYNC_HOURS` (hora de `DEFONTANA_TIMEZONE`, días hábiles) | `DEFONTANA_ORDERS_SYNC_ENABLED` |
  | Diaria | Lotes + foto de stock del ERP | `DEFONTANA_STOCK_SYNC_AT` (03:30); si falla, reintenta a la hora siguiente | `DEFONTANA_STOCK_SYNC_ENABLED` |
  | A demanda | Botones de la pantalla de Defontana e informe de stock | Cuando alguien lo pide | — |

  Si un envío al ERP agota sus reintentos, ahora avisa a los supervisores
  (notificación `sync_job_failed`, lleva a la Cola de Sincronización): antes quedaba
  descuadrado en silencio.
- **Flujo 3 — Guía de despacho → `Order/DispatchOrder`** *(pendiente de valores)*. Falta el
  mapeo de `dispatchInfo` (tipo de bien `1` "Constituye una venta", tipo de despacho `1` "Por
  cuenta del cliente") y `originStorageInfo.motive`.
- **Reemplazo de productos en picking** *(replantear: `UpdateOrder` NO sirve)*.
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
  importador de Excel**; decidir si además se crean desde ahí los productos que falten (solo
  código y nombre).
- **Informe "Stock ERP vs WMS"** *(hecho, informativo)*: "Traer stock de Defontana"
  (`Inventory/GetFutureStockInfo`: actual, reservado, por recibir) guarda una foto en
  `erp_stock`; Inventario → Stock ERP vs WMS la cruza con los saldos del WMS por SKU y bodega
  (vía `erp_storage_code`).
- **Modelo de stock decidido (2026-09-15): manda Defontana; el WMS ubica.** Ver
  `docs/entregables/Modelo-de-stock-con-Defontana.md`. Pendiente de construir:
  1. **Conciliación WMS ← Defontana**: *(vista previa hecha)* Inventario → Stock ERP vs WMS →
     "Calcular conciliación" muestra qué sumaría (con los lotes del ERP, en la ubicación de
     entrada configurable `DEFONTANA_RECONCILE_LOCATION_CODE`) y qué descontaría por FEFO, sin
     modificar nada. **Falta el "aplicar"**: escribir los ajustes con movimiento auditable
     (esos ajustes NO deben viajar a Defontana) y luego automatizarlo. Pendiente definir cada
     cuánto corre y qué hacer con diferencias grandes.
  2. ~~Push de ajustes y mermas~~ *(hecho)*: el ajuste viaja a `Inventory/Insert` como documento
     de entrada o salida (`XAJ_ENT_UN` / `XAJ_SAL_UNID`, configurables). El WMS no tiene
     transferencia entre bodegas, y la de ubicaciones no cambia el total: no se envía.
  3. **Lotes del ERP en la operación** (elegir lote conocido con su vencimiento al recibir/ubicar).
  4. **Ubicar stock recibido en Defontana** sin volver a sumarlo en el WMS.

  Preguntas abiertas en el documento: dónde se registra la recepción, quién hace ajustes y
  mermas, cada cuánto se concilia y qué hacer con diferencias grandes.
- **Bodegas** *(hecho)*: se administran **solo en el WMS**; se eliminó la sincronización de
  bodegas desde Defontana (botón, endpoint, job y conector).

---

## Pendiente (funcional)

- **Endpoints reales de Defontana para crear producto / crear pedido.** La
  integración hoy sólo **lee** productos y pedidos desde Defontana; su API no
  expone (o no se ha confirmado) endpoints para **crear** un producto o un pedido.
  Por eso los jobs `create_product` y `create_order` responden OK en mock y lanzan
  `NotImplementedError` en modo real, y las acciones "Nuevo producto / pedido" están
  ocultas en la UI (flag `ERP_CREATE_ENABLED` en `frontend/src/config.ts`). Cuando
  se confirmen los endpoints reales, conectarlos en `DefontanaConnector.create_product`
  / `create_order` (`backend/app/integrations/defontana/client.py`) y poner el flag en true.
  *(Actualización 2026-09: Pedidos sí expone `Order/SaveOrder` / `UpdateOrder`; crear productos
  es `Sale/SaveProduct`, del módulo Ventas, no contratado. La recepción → `Inventory/Insert`
  está probada en pruebas pero el payload del WMS aún no tiene el formato real: ver
  "Integración Defontana".)*

- **Nombre y logo del producto.** Pendiente de definir (lo verá el dueño). Cuando esté,
  aplicar en: ícono/logo, nombre en el menú (`Layout.tsx`) y favicon.

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
