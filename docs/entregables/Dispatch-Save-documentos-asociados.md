# `attachedDocuments` — códigos de documento asociado

Catálogo de `documentTypeId` válidos para el arreglo `attachedDocuments` de `Dispatch/Save`
(guía de despacho, B.1). Lo entregó Defontana (Luis) el 2026-09-25 en
`G - TIPOS DE DOCUMENTOS ASOCIADOS.xlsx`.

En el flujo del WMS la **Nota de Pedido (`802`) siempre va**: es lo que mueve el estado del pedido
al emitir la guía. Se pueden sumar más documentos (Orden de Compra, etc.); esos los define el
cliente.

| Código | Descripción |
|---|---|
| `50` | Guía de Despacho |
| `52` | Guía de Despacho Electrónica |
| `801` | Orden de Compra |
| `802` | Nota de Pedido |
| `803` | Contrato |
| `804` | Resolución |
| `807` | DUS |
| `808` | B/L Conocimientos de embarque |
| `809` | AWB |
| `810` | MIC/DTA |
| `811` | Carta de Porte |
| `812` | Resolución de SNA - Servicios de Exportación |
| `813` | Pasaporte |
| `820` | Cod. Inscrip. Reg. Acuerdos Pzo. Pago Exc. |
| `CEC` | Centro de Costo |
| `CIF` | Carta de Instrucción de Facturación |
| `EM` | Entrada de Mercadería |
| `EP` | Estado de Pago |
| `GRN` | Goods Receipt Notice |
| `HAS` | HAS |
| `HES` | HES |
| `HEP` | Hoja de Entrega de Productos |
| `ICS` | Nota de Recepción |
| `LT` | Lote de Viaje |
| `NRB` | Notificación de Recepción de Bienes |
| `OST` | Orden de Servicio a Terceros |
| `OV` | Recepción de Servicios |
| `PF` | Prefactura |
| `SEN` | Sistema Eléctrico Nacional |
| `SUC` | Sucursal |
| `UDP` | Unidades de Pago |
| `CON` | Conformidad |
| `HEM` | Recepción de Material |

> Nota: el `.md` de descripción de campos de Defontana dice que `documentTypeId` es "el código del
> documento en el SII (33 - 34 - etc)", pero el ejemplo real usa estos códigos (`802`, `801`…), que
> son los de esta lista, no los tipos DTE del SII. Se sigue la lista.
