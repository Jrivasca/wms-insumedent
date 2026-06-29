# Roadmap / Pendientes

Mejoras acordadas para más adelante. No bloquean la demo actual.

## Pendiente

- **Endpoints reales de Defontana para crear producto / crear pedido.** La
  integración hoy sólo **lee** productos y pedidos desde Defontana; su API no
  expone (o no se ha confirmado) endpoints para **crear** un producto o un
  pedido. Por eso los jobs `create_product` y `create_order` responden OK en
  mock y lanzan `NotImplementedError` en modo real. Cuando se confirmen los
  endpoints reales, conectarlos en `DefontanaConnector.create_product` /
  `create_order` (`backend/app/integrations/defontana/client.py`).
  *(La recepción → `Inventory/Insert` sí sincroniza de verdad.)*

## Hecho (referencia rápida)

- Catálogo dental real de INSUMEDENT en la demo (1251 productos con stock real, 17 categorías).
- Flujo completo **picking → packing → despacho** clickeable, operable sin pistola lectora.
- Escáner con **soporte móvil**: cámara para escanear + teclado en pantalla al tocar.
- **"Volver a escanear"** para corregir líneas en picking y packing.
- **Retomar** tareas en curso: filas clickeables en Picking/Packing y "Continuar picking" en Pedidos.
- **Impresión de etiquetas** con código de barras EAN-13 escaneable (A4 o impresora térmica).
- **Recepción de mercadería** (con ubicación → etiqueta → sync ERP real vía `Inventory/Insert`).
- **Alta de producto** y **alta de pedido** desde la UI, con job de sincronización al ERP.
- **Paginación** de listados (productos, saldos, movimientos).
- **Submenú Inventario** (Saldos / Recepción / Transferencia / Ajuste) con selector de producto.
- **Transportista** como lista desplegable (Bluexpress / NewTrans / Otro).
