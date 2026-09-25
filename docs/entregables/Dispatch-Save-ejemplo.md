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

**Valores que definió Insumedent (según el ejemplo de Luis, a confirmar por contabilidad):**

- **`documentType`** = `GDVELECT`.
- **Cuentas** (`accountNumber`): cliente `1110401001`; venta e inventario de línea `1110801001`;
  inventario de bodega `4110101001`. En el código van por config (`defontana_dispatch_*_account`);
  hoy vacías hasta la confirmación contable.
- **`motive`** de la bodega = `VENTA`.

**Diferencias del payload del WMS respecto al ejemplo de Luis (esperadas):**

- `externalDocumentID` lleva un identificador interno del WMS (`WMS-GD-<id>`), no vacío: sirve para
  correlacionar la guía con el despacho.
- `firstFeePaid` = `emissionDate`: el WMS aún no calcula el vencimiento de la cuota según la
  condición de pago (ver pregunta abierta).
- `attachedDocuments` trae solo la Nota de Pedido; la Orden de Compra la suma Insumedent si aplica.

**Preguntas abiertas para Luis:**

1. **Casing:** ¿el endpoint exige los campos en minúscula inicial (`documentType`, `clientFile`…),
   o los acepta también en mayúscula? Lo dejamos igual a tu ejemplo.
2. **Cuentas:** ¿confirmás que son las definitivas y a qué asiento va cada una? ¿El
   `analysisInventory` de la línea (`1110801001`) va distinto al `storageAnalysis` de la bodega
   (`4110101001`) a propósito?
3. **`businessCenter`:** ¿va solo en `storageAnalysis` y vacío en cliente y líneas, como en tu
   ejemplo?
4. **`attachedDocuments`:** ¿es obligatorio, o basta con la Nota de Pedido? ¿`documentTypeId 802` es
   siempre Nota de Pedido y `801` Orden de Compra?
5. **`firstFeePaid`:** ¿lo calcula el ERP a partir de la condición de pago, o hay que mandarlo con la
   fecha de vencimiento de la primera cuota?
