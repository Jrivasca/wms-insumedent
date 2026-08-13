# Análisis y diseño — Integración Defontana en el WMS

**Objetivo:** decidir *qué APIs de Defontana contratar* (el ERP cobra por API) y
definir el diseño de la integración, incluyendo qué se desarrolla para reemplazar
las APIs que se decide no contratar.

| | |
|---|---|
| **Fecha** | 2026-08-12 · **actualización v2: 2026-08-13** |
| **Sistema** | WMS Insumedent — FastAPI · MongoDB · React, con capa de conectores ERP |
| **Fuentes** | Swagger de pruebas `replapi.defontana.com`, Swagger productivo `api.defontana.com`, Wiki "API REST INTEGRACIÓN v1.0.0 – LIVE", y el conector implementado en `backend/app/integrations/defontana/` |

---

## Actualización v2 (2026-08-13) — modelo "por archivos" ya implementado

Tras revisar el Swagger y decidir minimizar APIs con automatizaciones por archivos, se
refina la recomendación y se implementó el reemplazo. **Lo construido no depende de
contratar nada** (opera stand-alone):

- **Pedidos — ya NO se contrata la lectura.** El intake pasa a **PDF-watch**: un worker
  lee los PDFs que Defontana deja en una carpeta de nube sincronizada y crea el pedido
  (o lo manda a una cola de revisión si el match no es limpio). *Implementado* (folder
  `pedidos/`, híbrido). Como la orden ya existe en Defontana (el PDF es su documento), no
  hay que empujar pedidos al ERP.
- **Productos — ya NO se contrata Ventas.** Importador de **Excel** (subida manual o
  folder-watch `productos/`), con validación de `Code` obligatorio, todo-o-nada y
  recordatorio si no hay carga en 24 h. *Implementado*.
- **Lotes y vencimiento — en el WMS**, no en Defontana: recepción con lote+fecha, picking
  **FEFO** y alerta "por vencer". *Implementado*. `Inventory/Insert` ya acepta `lotNumber`;
  el vencimiento no requiere API.
- **Recomendación de contratación afinada: 2 APIs = Inventario + Guía de despacho**
  (con caída limpia a **1 = solo Inventario**, dejando la guía manual con el folio tipeado
  en el WMS, que ya está soportado). El "Pedidos" del cuadro de abajo se reduce a la
  **escritura de despacho** (confirmar salida / emitir guía), no a la lectura de pedidos.

**Hallazgos del Swagger (corrigen §3 y §9):**
- **`Inventory/Insert` es POST, no PUT** — el conector usa `PUT`; hay que corregirlo en el
  cutover (Fase 4). Confirmado contra el Swagger de pruebas.
- Existe un **módulo `Dispatch/*` separado** (`Dispatch/Save`, `InsertDocument`,
  `SaveAsyncStockMovement`). Sigue pendiente confirmar con Defontana si la guía (DTE) sale
  por ahí o por `Order/DispatchOrder` (define cuál es la 2ª API).

**Estado:** el cutover a las APIs contratadas (PUT→POST, apuntar a producción, folio de
guía) y el recorte del código de sync ya muerto quedan para **cuando se contrate Defontana**
(Fases 3+4 del plan). El resto del modelo por archivos ya está en el WMS.

El resto del documento es el análisis original (v1), que sigue vigente salvo por los dos
hallazgos del Swagger y la reducción de "Pedidos" a la escritura de despacho.

---

## 1. Resumen ejecutivo

**Se contratan 2 APIs: Inventario y Pedidos.** Ambas ya están implementadas en el
conector, por lo que contratarlas no implica desarrollo nuevo: solo apuntar a
producción.

**No se contrata Ventas (Sale).** Aunque es la fuente del maestro de productos y
bodegas, su función se reemplaza por dos mecanismos internos: una **carga diaria
por Excel** para productos y un **mantenedor manual** para bodegas. Esto exige
construir un importador (5 componentes, detallados en §6), de los cuales 3
reutilizan código ya existente.

**Se descartan** Contabilidad y Cotizaciones. **Se posponen** Órdenes de Compra y
Compras hasta que se implemente el match de recepción.

| Módulo | Decisión | Desarrollo asociado |
|---|---|---|
| **Inventario** | Contratar | Ninguno — ya implementado |
| **Pedidos** | Contratar | Ninguno — ya implementado |
| **Guía de Despacho** | Evaluar antes de firmar | Depende de la respuesta de Defontana |
| **Ventas (Sale)** | **No contratar** | Importador de Excel + mantenedor de bodegas |
| Órdenes de Compra | Fase 2 | Cuando exista match de recepción |
| Compras | Fase 2 / opcional | Idem |
| Contabilidad | Descartar | — |
| Cotizaciones | Descartar | — |

---

## 2. Contexto y principio de diseño

El WMS es el sistema maestro de la **operación física de bodega** (inventario,
ubicaciones, picking, packing, despacho y recepción). Defontana se mantiene como
sistema maestro **comercial, documental y contable**. La integración vive en una
capa separada (`ERPConnector` + `DefontanaConnector`) y **nunca bloquea** la
operación: los cambios se sincronizan de forma asíncrona vía la cola `sync_jobs`.

De ahí la regla de decisión:

> **Solo se contrata la API que alimenta o recibe datos de un flujo físico del
> WMS, y únicamente cuando no existe una alternativa interna razonable.** Todo lo
> comercial, documental o contable que el WMS no toca se queda en Defontana.

---

## 3. Estado actual del conector (evidencia en código)

`client.py` invoca exactamente estos endpoints:

| Método del conector | Endpoint | Módulo | Uso |
|---|---|---|---|
| `get_products` | `GET /sale/GetSimpleProducts` | Ventas | Sincronizar catálogo |
| `get_product_by_barcode` | `GET /sale/GetProductsPOSByBarCode` | Ventas | Buscar producto al escanear |
| `get_warehouses` | `GET /sale/GetStorages` | Ventas | Sincronizar bodegas |
| `get_orders` | `GET /Order/List` | Pedidos | Traer pedidos a preparar |
| `dispatch_order` | `POST /Order/DispatchOrder` | Pedidos | Confirmar despacho |
| `create_inventory_document` | `PUT /Inventory/Insert` | Inventario | Recepción / ajuste / transferencia |
| `get_inventory_document_by_external_id` | `GET /Inventory/GetDocumentByExternalDocumentID` | Inventario | Idempotencia |
| `create_product` / `create_order` | *(sin endpoint confirmado)* | — | Mock; `NotImplementedError` en modo real |

Solo tres módulos se usan realmente: **Ventas, Pedidos e Inventario**. Los demás
no se invocan en ningún punto del código.

> ⚠️ **A verificar:** el conector usa `PUT` para `Inventory/Insert`, pero la
> documentación oficial indica que **PUT, PATCH y DELETE no están disponibles** —
> solo GET (lectura) y POST (creación). Confirmar el verbo correcto contra el
> Swagger de pruebas antes de pasar a producción.

---

## 4. Análisis por módulo

### 4.1 Inventario — CONTRATAR (núcleo)

Es la única API por la que el WMS **escribe** en Defontana. Cada recepción, ajuste
y transferencia se materializa como documento de inventario vía `Inventory/Insert`,
y `GetDocumentByExternalDocumentID` garantiza idempotencia ante reintentos.

Los 12 endpoints del módulo son: `InsertDocument`, `Insert`, `InsertSkipCentralization`,
`GetDocument`, `Delete`, `UpdateDocument`, `UpdateDocumentSkipCentralization`,
`GetDocumentByExternalDocumentID`, `List`, `GetBatchesInfo`, `GetFutureStockInfo`,
`GetTypeInventoryInfo`. Todos operan sobre **movimientos y documentos**;
**ninguno expone el maestro de productos ni el de bodegas** — dato relevante para
la decisión sobre Ventas (§4.3).

Sin esta API, el stock físico del WMS y el del ERP quedan desincronizados de forma
permanente. **No es opcional.**

### 4.2 Pedidos — CONTRATAR (esencial)

Alimenta el flujo **Pedidos → Picking → Packing → Despacho**: `Order/List` trae los
pedidos a preparar y `Order/DispatchOrder` confirma la salida. Es la razón de ser
operativa del WMS del lado de salida.

### 4.3 Ventas (Sale) — NO CONTRATAR, se reemplaza

Este módulo expone el **maestro de productos** (`GetSimpleProducts`), la búsqueda
por **código de barras** (`GetProductsPOSByBarCode`) y el listado de **bodegas**
(`GetStorages`).

**Por qué parecía imprescindible:** cuando el WMS envía una recepción vía
`Inventory/Insert`, el documento debe llevar el **código de producto y el código de
bodega tal como los identifica Defontana** — no el SKU ni la ubicación interna del
WMS. Sale era la fuente de esa tabla de equivalencias.

**Por qué se puede reemplazar:** lo que realmente se necesita de Sale es el campo
**`Code`** de cada producto y el código de cada bodega. Ninguno de los dos requiere
una API para llegar al WMS:

| Dato | Reemplazo | Frecuencia |
|---|---|---|
| Maestro de productos (incl. `Code` y barcode inicial) | Exportación Excel desde Defontana → importador en el WMS | Diaria |
| Bodegas / storages | Mantenedor manual en el WMS | Una vez, al crear la bodega |
| Búsqueda por código de barras | Catálogo local (`products` + `barcodes`) | Tiempo real, sin ERP |

El escaneo ya se resuelve contra el catálogo local, y el WMS gestiona sus propios
códigos de barras. El alta de producto nuevo pasa a ocurrir **siempre en
Defontana**, y llega al WMS en la importación siguiente — algo coherente con la
situación actual, donde `create_product` no tiene endpoint confirmado.

**Condición crítica:** el Excel exportado debe traer el campo **`Code`** de
Defontana tal cual. Es el mismo valor que hoy el mapper guarda como
`sku` / `erp_product_id`, y el que `Inventory/Insert` necesita para que el
movimiento cuadre. Sin ese campo, el reemplazo no funciona.

### 4.4 Guía de Despacho — EVALUAR antes de firmar

El WMS despacha físicamente, pero la guía de despacho es un **documento tributario
(DTE)** que el conector hoy no emite. Hay que confirmar con Defontana:

- Si `Order/DispatchOrder` (módulo Pedidos) **ya emite** la guía asociada al pedido
  → **no** se contrata Guía de Despacho.
- Si el DTE requiere el módulo específico `Dispatch/*` (3 endpoints POST en el
  Swagger) → **sí** debe contratarse.

Es la única contratación con incertidumbre real, y el único punto legal/documental
que toca un flujo físico (la salida de mercadería).

### 4.5 Órdenes de Compra — FASE 2

Hoy la recepción es un movimiento de stock simple, sin cotejo contra un documento
previo. El levantamiento de *alertas de recepción y match* apunta a comparar lo
recibido contra lo esperado, y ese "esperado" natural es la **orden de compra**.
Contratar cuando se implemente ese flujo, no antes.

### 4.6 Compras — FASE 2 / opcional

Relevante solo si el match se hace contra la **factura de compra** en vez de (o
además de) la OC. Depende de la decisión funcional de §4.5.

### 4.7 Contabilidad — DESCARTAR

Defontana sigue siendo el maestro contable; el WMS no genera ni consume asientos.
Es el módulo más grande del Swagger (~40 endpoints) y ninguno aplica a bodega.

### 4.8 Cotizaciones — DESCARTAR

Paso comercial **previo** al pedido. El WMS entra cuando ya hay un pedido
confirmado a preparar. Fuera de alcance.

---

## 5. Arquitectura resultante

Tres canales, dos por API y uno batch:

```
DEFONTANA ERP                CANAL                          WMS
─────────────────────────────────────────────────────────────────────────
Pedido de venta      ←──  API Pedidos (tiempo real)  ──→   Picking → Packing
confirmado                Order/List · DispatchOrder        → Despacho
                          ✓ ya implementado

Documento de         ←──  API Inventario (tiempo real) ──   Recepción · ajuste
inventario                Inventory/Insert                   transferencia
                          ✓ ya implementado

Maestro de           ┄┄→  Excel diario                 ┄┄→  Catálogo local
productos                 IMPORTADOR A DESARROLLAR          products + barcodes
(alta ocurre aquí)        campo clave: Code

Bodegas              ┄┄→  Mantenedor manual (carga única) ─→ Ubicaciones
```

El diagrama en detalle está en `Flujo-Integracion-Defontana.svg` (misma carpeta).

---

## 6. Desarrollo requerido para productos

Reemplaza a `sync_products()`, que hoy llama a `Sale/GetSimpleProducts`.

| # | Componente | Qué hace | Esfuerzo |
|---|---|---|---|
| 1 | **Endpoint de carga** | `POST /products/import`, recibe el `.xlsx`, restringido a rol supervisor | Nuevo (reutiliza la autenticación por rol existente) |
| 2 | **Parser + validación** | Lee las columnas, valida que `Code` venga en toda fila, detecta filas malformadas. Rechaza el archivo completo sin aplicar cambios parciales | **Nuevo — el grueso del trabajo** |
| 3 | **Mapper de Excel** | Convierte cada fila al documento del WMS | Adapta `DefontanaMapper.map_product()`; solo cambia la fuente de datos |
| 4 | **Upsert + barcodes** | Crea o actualiza producto por SKU y agrega códigos de barras nuevos | **Ya existe** dentro de `sync_products()`; se extrae y reutiliza |
| 5 | **Reporte + alerta** | Devuelve creados / actualizados / rechazados, y avisa si no hubo carga en 24 h | Nuevo, pequeño pero **no omitir** (ver §7) |

**Se reutiliza sin cambios:** colecciones `products` y `barcodes`, la lógica de
upsert, `DefontanaMapper.map_product()`, la autenticación por rol y la pantalla de
catálogo.

**Bodegas:** mantenedor manual simple. Se carga el código de bodega de Defontana
una sola vez y solo se toca si se abre una bodega nueva. No requiere Excel ni API.

---

## 7. Riesgos de la decisión y mitigación

| Riesgo | Impacto | Mitigación |
|---|---|---|
| **Nadie sube el archivo un día** | El catálogo queda desactualizado en silencio; con la API el worker lo hacía solo | Alerta del componente 5: avisar si no hubo carga en 24 h |
| **Desfase de hasta 24 h** | Un producto creado hoy en Defontana no se puede recibir/despachar hasta mañana | Permitir carga manual bajo demanda, además de la diaria |
| **El Excel no trae `Code`** | El importador no puede amarrar con `Inventory/Insert` | Validación bloqueante en el componente 2 |
| **Dependencia de una persona** | Proceso manual sin respaldo | Documentar el procedimiento y dejarlo con dos responsables |
| **Verbo PUT no soportado** | `Inventory/Insert` podría fallar en producción | Verificar contra el Swagger de pruebas (§3) |

---

## 8. Ambiente de pruebas

Defontana dispone de un entorno de pruebas; el ambiente se determina por la URL.

| Ámbito | URL base | Swagger |
|---|---|---|
| Pruebas | `https://replapi.defontana.com` | `/swagger/index.html` |
| Producción | `https://api.defontana.com` | `/swagger/index.html` |

El conector hoy apunta a `replapi`, es decir al ambiente de pruebas.

**Comportamiento a tener en cuenta:**

- Opera sobre una **base de datos de replicación** de producción.
- Se **actualiza semanalmente** desde producción: todo lo creado o configurado en
  pruebas durante la semana **se pierde**. Por eso Defontana recomienda hacer las
  configuraciones y maestros directamente en producción, para que se repliquen.
- **Disponible lunes a viernes, 09:00–20:00.** Sábado y domingo no disponible.

**Autenticación:** token JWT vía `/api/auth` (parámetros `Client`, `Company`,
`User`, `Password`). Cada token nuevo **invalida los anteriores del mismo usuario**,
por lo que procesos en paralelo requieren centralizar el token — que es exactamente
lo que hace `token_manager.py` (un token por tenant, cifrado y reutilizado).

---

## 9. Preguntas a confirmar con Defontana

1. ¿La **guía de despacho** (DTE) se emite dentro del módulo Pedidos
   (`Order/DispatchOrder`) o requiere contratar el módulo **Guía de Despacho**?
2. ¿`Inventory/Insert` se consume por **POST** (la doc indica que PUT no está
   disponible)?
3. Modelo de cobro exacto: ¿precio **por módulo**, por volumen de llamadas, o ambos?
4. Límites de *rate* por API contratada.
5. ¿La exportación del maestro de productos desde el ERP incluye el campo **`Code`**
   y el código de barras? (condición para el diseño de §4.3)

---

## 10. Cierre

Para operar el WMS en producción bastan **dos APIs contratadas: Inventario y
Pedidos**, ambas ya implementadas. El catálogo de productos se resuelve con un
**importador de Excel diario** y las bodegas con un **mantenedor manual**, evitando
contratar Ventas a cambio de construir 5 componentes —tres de los cuales reutilizan
código existente— y de asumir un proceso operativo manual con hasta 24 h de desfase.

La **Guía de Despacho** queda pendiente de una consulta puntual. **Órdenes de Compra
y Compras** se reservan para la fase de match de recepción, y **Contabilidad y
Cotizaciones** quedan fuera del alcance del WMS.
