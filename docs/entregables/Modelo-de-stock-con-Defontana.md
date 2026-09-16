# Modelo de stock: Defontana manda, el WMS ubica

> Decisión del 2026-09-15. Contexto: APIs contratadas = **Inventario, Pedidos y Guías de
> Despacho** (Ventas no). Detalle técnico de la integración en
> `Analisis-APIs-Defontana-a-contratar.md` (v3).

## 1. La decisión

- **Defontana es la fuente de verdad de las CANTIDADES.** Si el WMS y el ERP no coinciden,
  gana Defontana.
- **El WMS es la fuente de verdad de la UBICACIÓN física** (bodega → ubicación → lote/serie) y
  de la operación: picking, packing, despacho, etiquetas.
- **El catálogo de productos sigue llegando por el importador de Excel.** Ningún endpoint
  contratado entrega el maestro completo.
- **Los lotes y vencimientos se traen del ERP** (`Inventory/GetBatchesInfo`).

Consecuencia práctica: el stock del WMS deja de ser un registro independiente y pasa a ser un
**espejo del ERP con ubicaciones encima**.

## 2. Reglas que se derivan

1. **Toda operación que cambia la cantidad total debe llegar a Defontana.** Recepción, ajuste,
   merma y transferencia entre bodegas se envían con `Inventory/Insert`. Si el envío falla, la
   operación queda marcada y visible, no "silenciosamente local".
2. **Las operaciones que solo mueven mercadería dentro de la misma bodega son del WMS.**
   Transferencia entre ubicaciones, movimientos de picking a staging y de staging a packing: el
   ERP no modela ubicaciones y su total no cambia, así que no se envían.
3. **El despacho baja stock en el ERP con la guía** (`Order/DispatchOrder`), no con un
   documento de inventario aparte.
4. **Conciliación periódica:** el WMS compara su stock con el del ERP y, ante diferencia, se
   ajusta al ERP dejando un movimiento de conciliación auditable. Nunca al revés.

## 3. Impacto por funcionalidad

| Funcionalidad | Qué pasa | Por qué |
|---|---|---|
| **Recepción de mercadería** | **Se mantiene**, pero obligatoriamente empuja a Defontana (`Inventory/Insert`, ya implementado y apagado hasta confirmar tipo de documento y motivo). Si el push falla, la recepción queda "pendiente de ERP". | Cambia la cantidad total |
| **Ajuste de inventario** (supervisor) | **Se mantiene, con cambio**: hoy NO se envía a Defontana. Debe enviarse como documento de ajuste (`XAJ_ENT_UN` / `XAJ_SAL_UNID`) o quitarse del WMS y hacerse en el ERP. | Cambia la cantidad total |
| **Merma** | Igual que el ajuste: enviar como `MM` o hacerla en el ERP. | Cambia la cantidad total |
| **Transferencia entre bodegas** | **Se mantiene, con cambio**: hoy NO se envía. Debe enviarse con bodega de origen y destino. | Cambia el stock por bodega en el ERP |
| **Transferencia entre ubicaciones** (misma bodega) | **Se mantiene tal cual**, solo en el WMS. | El ERP no tiene ubicaciones |
| **Picking / packing** | **Sin cambios.** Los movimientos a staging y packing son internos. | El total de la bodega no cambia |
| **Despacho** | **Sin cambios de modelo**: la guía en Defontana es la que baja el stock. Falta conectar `Order/DispatchOrder` (pendiente de valores). | — |
| **Lotes y vencimientos** | **Cambian de origen**: se traen del ERP en vez de capturarse solo en la recepción. El WMS sigue asignando en qué ubicación está cada lote. | Decisión tomada |
| **FEFO y alerta "por vencer"** | **Se mantienen**, alimentados por los vencimientos del ERP. | — |
| **Alerta de stock cero y aviso de reposición** | **Se mantienen**, pero pasan a dispararse también cuando la conciliación detecta que llegó stock en el ERP. | El stock ahora entra por el ERP |
| **Catálogo de productos** | **Sigue por Excel.** "Sync lotes" solo cubre los artículos con lote. | No hay API del maestro |
| **Bodegas** | **Solo en el WMS**, pero su `erp_storage_code` debe coincidir con el código de Defontana: es la llave del cruce. | — |
| **Informe "Stock ERP vs WMS"** | **Se mantiene** y pasa a ser la antesala de la conciliación. | — |

## 4. Lo que hay que construir

1. **Conciliación WMS ← Defontana** *(núcleo del modelo)*. A partir de la foto de
   `GetFutureStockInfo` y de los lotes de `GetBatchesInfo`:
   - Ajusta los saldos del WMS a los del ERP, por producto y bodega.
   - Deja un movimiento de conciliación (auditable) por cada corrección.
   - **Dónde ubicar lo que sobra:** el ERP no sabe de ubicaciones. Lo que aparece de más se
     deja en una ubicación de entrada (p. ej. `RECEPCION` o `SIN UBICAR`) para que bodega lo
     ubique; lo que falta se descuenta respetando FEFO.
   - Manual primero (botón, con vista previa) y automática después.
2. **Push a Defontana de ajustes, mermas y transferencias entre bodegas**, con los mismos
   valores configurables que la recepción.
3. **Lotes del ERP en la operación**: al recibir o ubicar, elegir de los lotes que Defontana ya
   conoce, con su vencimiento, en vez de escribirlos a mano.
4. **Ubicación de lo recibido**: si la recepción se registra en Defontana (por compras), el WMS
   debe permitir "ubicar" ese stock sin volver a sumarlo.

## 5. Preguntas abiertas

1. **¿Dónde se registra la recepción de mercadería: en el WMS o en Defontana (compras)?** Si se
   registra en Defontana, el WMS solo ubica y no envía nada; si se registra en el WMS, hay que
   cerrar el tipo de documento y el motivo con Defontana.
2. **¿Los ajustes y mermas los hará bodega desde el WMS** (y se envían al ERP) **o contabilidad
   en Defontana**? Si es lo segundo, esas pantallas salen del WMS.
3. **¿Cada cuánto se concilia?** Diaria de madrugada, o a demanda antes de cada jornada.
4. **¿Qué hacer con una diferencia grande?** Ajustar igual o dejarla para revisión humana.
