# Puesta en marcha: el día que el WMS empieza a operar de verdad

Procedimiento recomendado para el corte (*cutover*): pasar de "el WMS es una prueba" a "bodega
trabaja con el WMS", con Defontana como fuente de verdad de las cantidades.

La idea de fondo: **la conciliación deja todo el stock en `SIN-UBICAR`, que no es pickeable**, y
bodega lo va guardando en estantes con **Ubicar stock**. El picking se reactiva a medida que hay
stock en ubicaciones pickeables, no de golpe.

Antes de empezar, dos cosas que conviene tener claras:

- **Nada de esto viaja a Defontana.** La conciliación y el ubicado solo escriben en el WMS.
- **Todo es reversible mientras exista el respaldo.** El paso 6 exige uno, validado.

---

## 1. Antes del corte (se puede hacer con días de anticipación)

1. **Catálogo completo**: importar el Excel de productos. Un producto que Defontana tiene y el
   WMS no queda **bloqueado** en la conciliación: su stock no entra, así que no se puede ubicar
   ni pickear. La lista de faltantes está en `Productos-Defontana-no-en-WMS-*.csv`; hay que
   agregarlos antes del corte.
2. **Bodega**: `BODEGACENTRAL` con su `erp_storage_code` **idéntico** al código de Defontana. Si
   no coincide, la conciliación no propone nada para esa bodega (y lo dice en la fila, en vez de
   proponer vaciarla).
3. **Ubicaciones creadas e impresas**: los estantes reales, con su etiqueta. Deben existir
   también las operativas (`STAGING`, `PACKING`, `DISPATCH`, `QUARANTINE`) y `SIN-UBICAR`.
4. **Usuarios y roles** creados, y el usuario demo dado de baja o con otra contraseña.

## 2. Cerrar el trabajo en curso

Que no queden tareas abiertas al momento de la foto. Hoy **no hay un interruptor** que
pause la creación de tareas; en la práctica:

- Apagar la llegada de pedidos nuevos: `DEFONTANA_ORDERS_SYNC_ENABLED=false` y recrear el worker.
- Terminar los picking y packing que estén a medio hacer, o cancelarlos.
- Despachar lo que ya esté empacado.

## 3. Por qué importa lo que está en STAGING o PACKING

Es la pregunta que siempre aparece: *¿se va a duplicar el stock que está en preparación?*

**No se duplica.** La conciliación compara el total del ERP contra el **total del WMS en toda la
bodega**, y ese total ya incluye lo que está en `STAGING` y `PACKING`. Como esas unidades están
contadas, no se vuelven a sumar.

El riesgo real es el contrario. Defontana descuenta al emitir el documento de salida; si allá ya
se emitió y el WMS todavía tiene la mercadería en preparación, el ERP muestra **menos** que el
WMS y la conciliación querría descontar la diferencia. Por eso **el descuento excluye
`STAGING`, `PACKING` y `DISPATCH`**: esa mercadería está en la mano de un operario para un
pedido. Lo que no se puede descontar del resto queda explicado en la fila ("*N u están en
preparación…*") y pasa por aprobación humana.

Con el paso 2 hecho no debería quedar nada en esas ubicaciones y el punto es teórico. Si igual
aparecen filas así, significa que quedó trabajo a medias: termínalo y vuelve a conciliar.

## 4. Foto nueva de stock desde Defontana

Lanzar la sincronización de stock (o esperar la diaria de las 03:30). La conciliación **exige
una foto de menos de 12 horas**: con una vieja "corregiría" el WMS hacia un stock que ya no es
el del ERP, y se niega a correr.

## 5. Mirar antes de aplicar

En **Stock ERP vs WMS**, revisar la vista previa: cuántas filas, cuántas se aplican solas,
cuántas quedan para revisión y cuántas están bloqueadas. Las bloqueadas dicen por qué
(producto que no está en el catálogo, bodega mal configurada, todo lo sobrante en preparación).

## 6. Respaldo, y recién ahí conciliar

```bash
docker exec wms_mongo mongodump --db wms --archive=/tmp/antes-corte.gz --gzip
docker cp wms_mongo:/tmp/antes-corte.gz ./antes-corte-$(date +%F).gz
# validarlo: se lee completo sin escribir nada
docker exec -i wms_mongo mongorestore --archive --gzip --dryRun < ./antes-corte-$(date +%F).gz
```

Sin respaldo validado, no se aplica nada. Después, aplicar la conciliación: las diferencias
chicas se aplican solas y **las grandes quedan para revisión humana**, una por una.

## 7. Todo queda en SIN-UBICAR

Es lo esperado. Ese stock **no se ofrece al picking**: sirve para que los totales cuadren con
Defontana, pero bodega todavía no sabe dónde está físicamente.

## 8. Ubicar, en este orden

Con **Ubicar stock** (`/inventory/ubicar`), pensado para móvil y lector. El orden importa
porque el picking se reactiva a medida que hay stock ubicado:

1. **Productos de pedidos abiertos**: lo que hace falta para despachar hoy.
2. **Alta rotación**: lo que se pide todos los días.
3. **Próximos a vencer**: la vista de **Vencimientos** los muestra primero (FEFO). Lo vencido va
   a `QUARANTINE`, no a un estante de picking; la pantalla lo sugiere sola.
4. El resto, por pasillo, a ritmo normal.

## 9. Reactivar el picking de a poco

Volver a encender la llegada de pedidos (`DEFONTANA_ORDERS_SYNC_ENABLED=true`) cuando los
productos de esos pedidos ya estén ubicados. Si un pedido cae sobre un producto que sigue en
`SIN-UBICAR`, el picking no lo va a encontrar: quedará corto y aparecerá como parcial. No es un
error del sistema, es que ese producto todavía no se guardó.

## 10. Al final, la conciliación diaria

Recién cuando la bodega esté ubicada y el flujo corriendo:
`DEFONTANA_RECONCILE_ENABLED=true` (04:30, después de la foto de stock de las 03:30). Desde ahí
el WMS se mantiene solo, y lo grande sigue pasando por revisión humana.

---

## Si hay que volver atrás

```bash
docker exec -i wms_mongo mongorestore --archive --gzip --drop < ./antes-corte-FECHA.gz
```

Restaurar **borra lo hecho desde el respaldo**, incluido lo que bodega haya ubicado después. Por
eso conviene decidir temprano: si algo se ve mal en el paso 5 o 6, es el momento de parar.

## Verificaciones rápidas

| Qué mirar | Dónde | Qué esperar |
|---|---|---|
| Diferencias que quedan | Stock ERP vs WMS | Solo las de revisión y las bloqueadas, con su motivo |
| Stock sin ubicar | Ubicar stock | Baja a medida que bodega avanza |
| Vencidos | Vencimientos | Van saliendo hacia `QUARANTINE` |
| Envíos al ERP | Cola de sincronización | **Nada** por conciliar ni por ubicar |
| Movimientos | Inventario → últimos movimientos | "Conciliación con ERP" y "Transferencia" |
