# `Dispatch/Save` — ejemplo de payload (alineado con Defontana)

Ejemplo del payload que el WMS arma para `POST /api/Dispatch/Save` (guía de despacho, B.1).
Generado por el mapper `DefontanaMapper.build_dispatch_save` a partir de un **pedido real del
ambiente de pruebas** (Order/Get nº **2854**, I. Municipalidad de San Felipe). El JSON completo
está en [`Dispatch-Save-ejemplo.json`](./Dispatch-Save-ejemplo.json).

Esta versión **ya incorpora las correcciones que envió Luis (Defontana) el 2026-09-25**: claves en
camelCase con minúscula inicial, `attachedDocuments` con la Nota de Pedido, `saleTaxes` con IVA,
`businessCenter` solo en la bodega, y el tipo de documento / cuentas / `motive` con los valores de
su ejemplo.

**De dónde sale cada parte:**

- **Cabecera comercial** (cliente, condición de pago, vendedor, moneda, local, lista de precios,
  giro, comuna, región, precios de línea): del **pedido original** de Defontana (`Order/Get`).
- **`attachedDocuments`**: la **Nota de Pedido** que origina la guía — `documentTypeId: "802"`,
  `folio` = nº de pedido (2854). La **Orden de Compra** (`"801"`), cuando exista, la agrega
  Insumedent: el WMS no siempre la tiene (ver pregunta abierta abajo).
- **Líneas y lote** (`details` + `batchInfo`): del **despacho del WMS**. El lote lo elige el
  operario al pickear y viaja FEFO hasta la guía. Las dos primeras líneas llevan lote; la tercera va
  sin lote, para mostrar ambos casos.
- **`saleTaxes`**: IVA 19 % cuando hay al menos una línea afecta.
- **`dispatchInfo`**: `assetsType="1"` (constituye venta), `dispatchType="1"` (por cuenta del
  cliente), `transactionType="1"` (venta del giro), `isTransferDispatch=false`. Confirmados.
- **`isTransferDocument=true`**: registra y contabiliza la guía **sin enviarla al SII** (para
  probar sin emitir un DTE real; igual consume folio y no se puede borrar). En producción irá
  `false`.
- **`destinationStorage` = `originStorage`**: no es traslado entre bodegas.

**Valores que definió Insumedent (confirmados por Luis el 2026-09-25):**

- **`documentType`** = `GDVELECT`.
- **Cuentas** (`accountNumber`): salen del ERP y las define el cliente; son fijas salvo que él las
  cambie. Se ven en *Configuración → Inventario → Listado de Documentos → editar `GDVELECT` →
  Definición Contable*. Confirmadas en la captura de Luis: **Asiento por Inventario** =
  `1110801001` (MERCADERIAS) → `analysisInventory` de línea; **Asiento por Facturas por Recibir** =
  `4110101001` (COSTOS DE VENTAS) → `storageAnalysis` de la bodega. **Van distintas a propósito.**
  Faltan del ERP la cuenta de **cliente** (`1110401001` en el ejemplo) y la de **venta de línea**.
  En el código van por config (`defontana_dispatch_*_account`), hoy vacías hasta cargarlas.
- **`businessCenter`**: es **por cuenta** — se envía solo si esa cuenta está configurada para usar
  centro de negocio; si no, no se envía. En el ejemplo solo la de bodega (`EMPNEGVTAVTA000`) lo
  lleva. Se valida por cuenta con `api/Accounting/Analysis/GetBusinessCenterAnalysisItems` o el plan
  `api/Accounting/BusinessCenterPlan` — **módulo Contabilidad, que no tenemos contratado**, así que
  la configuración por cuenta la confirma Insumedent con su ERP.
- **`attachedDocuments`**: la **Nota de Pedido** (`documentTypeId 802`, folio = nº de pedido)
  **siempre va**, porque es lo que mueve el estado del pedido al emitir la guía. Se pueden sumar más
  (Orden de Compra `801`, etc.); esos los agrega el cliente. El catálogo de códigos está en
  `G - TIPOS DE DOCUMENTOS ASOCIADOS.xlsx` (802 Nota de Pedido, 801 Orden de Compra, 52 Guía
  Despacho Electrónica, 50 Guía de Despacho, 803 Contrato, 804 Resolución…).
- **`motive`** de la bodega = `VENTA`.

- **`firstFeePaid`** (vencimiento del primer pago): confirmado por Luis (2026-09-25). Al **contado**
  (`CONTADO`) = fecha de emisión; a **crédito** (`CREDITO30`, `CREDITO60`…) = emisión + los días del
  plazo, que el WMS toma del propio código de la condición (el ERP **no** lo calcula). En el ejemplo,
  `CREDITO30` → emisión 25-09 y `firstFeePaid` 25-10.
- **Casing:** confirmado — los campos van en **minúscula inicial**, tal como el Swagger de Defontana.

**Diferencias del payload del WMS respecto al ejemplo de Luis (esperadas):**

- `externalDocumentID` lleva un identificador interno del WMS (`WMS-GD-<id>`), no vacío: sirve para
  correlacionar la guía con el despacho.
- `attachedDocuments` trae solo la Nota de Pedido; los demás documentos (Orden de Compra, etc.) los
  suma Insumedent si aplica.

**Todas las dudas de estructura están cerradas.** Para encender la guía solo falta que Insumedent
cargue en la config (`defontana_dispatch_*_account`) las cuentas de **cliente** y **venta de línea**
que salen de su ERP (las de inventario ya están confirmadas).
