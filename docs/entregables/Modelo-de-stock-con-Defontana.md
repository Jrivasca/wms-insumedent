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

1. **Toda operación que cambia la cantidad total debe llegar a Defontana.** Recepción, ajuste y
   merma se envían con `Inventory/Insert` (módulo Inventario, **contratado**: cubre entradas,
   ajustes y mermas cambiando el tipo de documento). Si el envío falla, la operación queda
   marcada y visible, no "silenciosamente local".
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
| **Ajuste de inventario** (supervisor) | **Se mantiene.** Ya viaja a Defontana como documento de ajuste de entrada o de salida según el signo (`XAJ_ENT_UN` / `XAJ_SAL_UNID`, configurables). | Cambia la cantidad total |
| **Merma** | Es un ajuste negativo: viaja como ajuste de salida (o `MM`, cambiando la configuración). | Cambia la cantidad total |
| **Transferencia entre ubicaciones** (misma bodega) | **Se mantiene tal cual**, solo en el WMS. El WMS no tiene transferencia entre bodegas. | El ERP no tiene ubicaciones y el total no cambia |
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
   - **Hecho (2026-09-19):** manual desde Inventario → Stock ERP vs WMS y diaria a las 04:30,
     después de la foto de stock. Lo que falta queda en `SIN-UBICAR` (tipo recepción, no
     pickeable); lo que sobra se descuenta por FEFO; cada ajuste deja un movimiento
     "Conciliación con ERP" y no viaja a Defontana. Las diferencias de más de 20 unidades
     esperan la aprobación de un supervisor. Primera corrida hecha a mano el 2026-09-19: 721
     ajustes aplicados, 282 diferencias grandes esperando revisión.
2. ~~Push a Defontana de ajustes y mermas~~ **(hecho)**: el ajuste viaja como documento de
   entrada o de salida, con los mismos valores configurables que la recepción
   (`DEFONTANA_INVENTORY_SYNC_ENABLED` + tipos de documento y motivo).
3. **Lotes del ERP en la operación**: al recibir o ubicar, elegir de los lotes que Defontana ya
   conoce, con su vencimiento, en vez de escribirlos a mano.
4. ~~**Ubicación de lo recibido**~~ *(resuelto)*: si la recepción se registra en Defontana (por
   compras), esas unidades aparecen solas en `SIN-UBICAR` con la conciliación, y **Ubicar stock**
   (`POST /inventory/putaway`, pantalla `/inventory/ubicar`) las lleva a su estante. Mueve el
   saldo **exacto**, así que conserva lote, serie y vencimiento, y como no cambia el total de la
   bodega **no viaja nada al ERP**: una conciliación posterior no ve ninguna diferencia por haber
   ubicado stock.

### Lo que la conciliación nunca toca

El descuento por FEFO **excluye STAGING, PACKING y DISPATCH**. Esa mercadería ya está en la mano
de un operario para un pedido: si Defontana la descontó porque allá ya se emitió el documento, el
WMS la suelta cuando el pedido termina, no quitándosela al pedido. Lo que no se puede descontar
del resto queda explicado en la fila y pasa por aprobación humana (o se marca bloqueada, si todo
lo sobrante está en preparación). Por la misma razón, Ubicar stock tampoco reubica lo que está en
esas ubicaciones.

## 5. Preguntas abiertas

> **Resueltas (2026-09-15):** la recepción y los ajustes/mermas se siguen haciendo **en el WMS**
> y se envían a Defontana, porque el módulo Inventario contratado lo permite.
>
> **Resueltas (2026-09-19), decisiones de Insumedent:** tipos de documento y motivos definidos y
> probados (recepción `PE`/`COMPRA`, ajustes `XAJ_ENT_UN`/`ENTRADA` y `XAJ_SAL_UNID`/`SALIDA`).
> Queda solo el **centro de negocio**, que va dentro de cada documento; por eso el envío sigue
> apagado.

1. **¿Cada cuánto se concilia?** *Respondida:* **a diario de madrugada**, y también a demanda
   desde el WMS.
2. **¿Qué hacer con una diferencia grande?** *Respondida:* **revisión humana**. Sobre 20
   unidades no se aplica sola: la aprueba un supervisor.
3. **¿Y si una recepción se registró en Defontana** (por compras) **y no en el WMS?** Sigue
   abierta, pero ya no bloquea: si ocurre, la conciliación trae esas unidades a `SIN-UBICAR` y
   bodega las ubica con una transferencia. Solo falta saber si pasa, para anticipar cuánto se
   va a llenar esa ubicación.
