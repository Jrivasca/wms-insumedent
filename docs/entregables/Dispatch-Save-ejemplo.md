# `Dispatch/Save` — ejemplo de payload (para validar con Defontana)

Ejemplo real del payload que el WMS arma para `POST /api/Dispatch/Save` (guía de despacho, B.1).
Generado con el mapper `DefontanaMapper.build_dispatch_save` a partir de un **pedido real del
ambiente de pruebas** (Order/Get nº **2854**, I. Municipalidad de San Felipe), acotado a las dos
primeras líneas de artículo para que sea legible. El JSON completo está en
[`Dispatch-Save-ejemplo.json`](./Dispatch-Save-ejemplo.json).

**De dónde sale cada parte:**

- **Cabecera comercial** (cliente, condición de pago, vendedor, moneda, local, lista de precios,
  giro, comuna, región, precios de línea): del **pedido original** de Defontana (`Order/Get`), que
  es la fuente de esos datos. Acá salen con los valores reales del pedido 2854.
- **Líneas y lote** (`Details` + `BatchInfo`): del **despacho del WMS**. El lote lo elige el
  operario al pickear y viaja FEFO hasta la guía. En el ejemplo, la 1ª línea lleva dos lotes
  (`LOTE-2027A` ×3, `LOTE-2028B` ×1) y la 2ª va sin lote, para mostrar los dos casos.
- **`DispatchInfo`**: `AssetsType="1"` (constituye venta), `DispatchType="1"` (por cuenta del
  cliente), `TransactionType="1"` (venta del giro), `IsTransferDispatch=false`. Confirmados.
- **`IsTransferDocument=true`**: registra y contabiliza la guía **sin enviarla al SII** (para
  probar sin emitir un DTE real; igual consume folio y no se puede borrar). En producción irá
  `false`.
- **`DestinationStorage` = `OriginStorage`**: no es traslado entre bodegas.

**Lo que falta definir Insumedent (van marcados `<PENDIENTE: ...>` en el JSON):**

1. **`DocumentType`** — código del tipo de documento de la guía (`GetDocumentInfo`).
2. **Cuentas contables** (`AccountNumber`) de los asientos de **cliente**, **venta** e
   **inventario**.
3. **`Motive`** de la bodega de origen: en el ejemplo va `VENTA` (para un egreso de venta lo
   lógico es `VENTA` o `SALIDA`); confirmar cuál usa Insumedent.

**Preguntas para Luis:**

- ¿La estructura y los nombres de campo calzan con lo que espera `Dispatch/Save`?
- ¿`ContactIndex` es la dirección en texto (como acá) o un índice/código del contacto del cliente?
- ¿`PriceList` corresponde al `referenceNumberPricingID` del pedido?
- Para una guía de venta normal, ¿confirmás `Motive` y el tipo de documento a usar?
