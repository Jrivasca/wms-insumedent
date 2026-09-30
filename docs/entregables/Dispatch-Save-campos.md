# `Dispatch/Save` — descripción de campos (Guía de Despacho)

**Fuente:** Luis López (Defontana), adjunto `JSON - DISPATCH - SAVE.md` en el canal Slack
`integracion-insumedent`, 2026-09-23.

**Por qué este método y no `Order/DispatchOrder`:** Luis lo recomendó explícitamente para
Insumedent porque **permite enviar lote y serie por línea** (y mueve el estado del pedido), y
nosotros manejamos lotes y vencimientos. `Order/DispatchOrder` no soporta lotes. Endpoint:
`POST /api/Dispatch/Save`. El mapeo del WMS (`build_dispatch_order`, para `Order/DispatchOrder`)
queda **superado**: hay que rehacerlo para `Dispatch/Save`.

> Reproducción textual de la spec de Defontana. Los métodos citados (`GetDocumentInfo`,
> `GetClients`, etc.) son de la propia API para obtener los códigos válidos de cada campo.

## Cabecera del documento

| Campo | Descripción | Método / valores | Obligatorio |
|---|---|---|---|
| `DocumentType` | Código del tipo de documento a utilizar (largo 20) | `GetDocumentInfo` | Sí |
| `FirstFolio` | Número de documento (0 = toma el correlativo del ERP) | — | Sí |
| `LastFolio` | Número de documento (0 = toma el correlativo del ERP) | — | Sí |
| `ExternalDocumentID` | Código externo único para marcar cada documento | — | No |
| `EmissionDate` | Fecha de emisión (`Day`, `Month`, `Year`) | — | Sí |
| `FirstFeePaid` | Fecha de primer pago y de vencimiento (`Day`, `Month`, `Year`) | — | Sí |
| `ClientFile` | Código del cliente (largo 20) | `GetClients` | Sí |
| `ContactIndex` | Dirección del cliente (largo 200) | `GetClients` | Sí |
| `PaymentCondition` | Código de la condición de pago (largo 20) | `GetPaymentConditions` | Sí |
| `SellerFileId` | Código del vendedor (largo 20) | `GetSellers` | Sí |
| `BillingCoin` | Código de la moneda (largo 20) | `GetAllCoinsId` | Sí |
| `BillingRate` | Tasa de cambio (enviar `1` si es PESO) | `GetCoinsId` | Sí |
| `ShopId` | Código del local (largo 20) | `GetShops` | Sí |
| `PriceList` | Código de la lista de precio (largo 20) | `GetPriceList` | Sí |
| `Giro` | Giro del cliente (largo 100) | `GetClients` | Sí |
| `District` | Código de comuna (largo 50) | `GetClients` | Sí |
| `City` | Código de la región (largo 50) | `GetClients` | Sí |
| `Contact` | Contacto: **enviar `-1`** | — | Sí |
| `Gloss` | Glosa general del documento de venta | — | No |

### `ClientAnalysis` — asiento de cliente (Obligatorio)
`AccountNumber` (cuenta contable sin puntos, **Obligatorio**) · `BusinessCenter`
(`GetBusinessCenterAnalysisItems`, largo 20, Opcional) · `Classifier01` · `Classifier02`
(Opcionales).

### `AttachedDocuments` — documentos asociados (lista, puede ir vacía `[]`)
`Date` (`Day/Month/Year`) · `DocumentTypeId` (código SII: 33, 34, etc.) · `Folio` (número a
asociar) · `Reason` (comentario). Todos obligatorios si se envía un elemento.

### `IsTransferDocument` (Obligatorio)
- `false` → el documento **se registra, contabiliza y se envía al SII**.
- `true` → el documento **se registra y contabiliza, pero NO se envía al SII**.
  *(Útil para probar sin emitir un DTE real al SII; igual consume folio y no se puede borrar.)*

## Bodegas

### `OriginStorage` — bodega desde la que se descuenta
`Code` (`GetStorages`, **Obligatorio**) · `Motive` (motivo del movimiento, **Obligatorio**) ·
`StorageAnalysis` (asiento de inventario: `AccountNumber` obligatorio; `BusinessCenter`,
`Classifier01/02` opcionales).

### `DestinationStorage` — bodega de destino
Misma estructura que `OriginStorage`. **Si no es traslado entre bodegas, enviar la misma
información que la bodega de origen.**

## `DispatchInfo` — información de la guía de despacho

| Campo | Valores | Obligatorio |
|---|---|---|
| `AssetsType` (tipo de traslado de bienes) | `1` Constituye una venta · `2` Ventas por efectuar · `3` Consignaciones · `4` Entrega gratuita · `5` Traslados internos · `6` Otros traslados (no venta) · `7` Guía de devolución · `8` Traslado para exportación · `9` Venta para exportación | Sí |
| `DispatchType` (tipo de despacho) | `1` Por cuenta del cliente · `2` Por cuenta del emisor · `3` Interno | Sí |
| `TransactionType` (tipo de transacción) | `1` Venta del Giro · `2` Venta del activo Fijo · `3` Venta Bien Raíz | Sí |
| `IsTransferDispatch` | `false` guía normal (origin y destination pueden ser el mismo código) · `true` traslado entre bodegas (origin ≠ destination) | Sí |

**Para una guía de venta normal de Insumedent:** `AssetsType="1"`, `DispatchType="1"`,
`TransactionType="1"`, `IsTransferDispatch=false`. (`AssetsType`/`DispatchType` confirmados en
guías reales; `TransactionType="1"` = "Venta del Giro" confirmado por esta spec.)

## `Details` — líneas del documento (lista, 1 o más)

| Campo | Descripción | Método / valores | Obligatorio |
|---|---|---|---|
| `Type` | `A` artículo · `S` servicio (largo 1) | — | Sí |
| `IsExempt` | `false` afecto · `true` exento | — | Sí |
| `Code` | Código del artículo o servicio (largo 25) | `GetProducts` / `GetServices` | Sí |
| `Count` | Cantidad | — | Sí |
| `ProductName` | Nombre del artículo o servicio | `GetProducts` / `GetServices` | Sí |
| `ProductNameBarCode` | Código de barras | `GetProducts` / `GetServices` | No |
| `Price` | Precio | `GetProducts` / `GetServices` | Sí |
| `Comment` | Comentario de la línea (largo 4000) | — | No |
| `Unit` | Código de unidad | `GetUnits` | Sí |

- **`Discount`** (Opcional): `Type` (`0` monto fijo, `1` porcentaje) · `Value` (siempre en
  **negativo**: `-50` = descuento de 50, o 50% según `Type`).
- **`EspecificTax`** (Opcional): `Value` (impuesto específico del artículo).
- **`Analysis`** — asiento de venta (Obligatorio): `AccountNumber` obligatorio; `BusinessCenter`
  (`GetBusinessCenterAnalysisItems`), `Classifier01/02` opcionales.
- **`analysisInventory`** — asiento de inventario (Opcional): misma estructura que `Analysis`.
- **Lotes** — `UseBatch` (`true`/`false`, Opcional) + `BatchInfo` (lista, puede ir `[]`):
  `Amount` (cantidad del lote) · `BatchNumber` (número de lote).
- **Series** — `UseSeries` (`true`/`false`, Opcional) + `Serials` (lista, puede ir `[]`):
  `SerialStart`, `SerialSufix`, `SerialPrefix`.

## Impuestos y descuentos globales

- **`SaleTaxes`** — información de impuestos, solo si es afecto (Obligatorio): `Code`
  (`GetTaxes`) · `Value` (`GetTaxes`) · `TaxAnalysis` (asiento: `AccountNumber` obligatorio;
  `BusinessCenter`/`Classifier01/02` opcionales).
- **`VentaRecDesGlobal`** — recargos/descuentos globales (Opcional, puede ir `[]`): `Amount`
  (monto en pesos) · `ModifierClass` (`PV` porcentaje variable, `MF` monto fijo, `MV` monto
  variable, `PF` porcentaje fijo) · `Name` · `Percentage` (o `"0"`) · `Value`.
- **`CustomFields`** — campos personalizables (Opcional): `Name` · `Value` (`GetCustomFields`).

---

**Pendientes para armar el payload real (B.1):**
1. **Ejemplo de JSON de Luis**: él ofreció armar el extracto para un pedido puntual que le
   pasemos (venta normal, con lote, en `BODEGACENTRAL`). Falta enviarle el número de pedido.
2. **`Motive` de la bodega de origen**: es decisión de Insumedent (códigos `COMPRA`, `DEVOLUCION`,
   `ENTRADA`, `SALIDA`, `TRASPASO`, `VENTA`). Para un egreso de venta lo lógico es `VENTA` o
   `SALIDA`; el `COMPRA` que vimos en un movimiento real era engañoso.
3. **Cuentas contables** (`AccountNumber` de los asientos de cliente, venta, inventario e
   impuestos): definición del negocio / contabilidad de Insumedent.
