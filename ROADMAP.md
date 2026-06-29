# Roadmap / Pendientes

Mejoras acordadas para más adelante. No bloquean la demo actual.

## Pendiente

- **Transportista como lista desplegable.** Hoy, en *Despachos → Confirmar despacho*,
  el transportista es un campo de **texto libre**. Cambiarlo por una **lista
  predefinida** (Chilexpress, Starken, Blue Express, etc.) para que sea más rápido y
  sin errores de tipeo. *(Definido con el cliente; se trabaja después.)*

- **Paginación de listados.** `list_products` (productos) topea en **500** filas y
  `list_balances` (inventario) en **1000**, sin paginación. Con el catálogo completo
  (1251 productos) las vistas de listado no muestran todo —la **búsqueda** sí encuentra
  cualquiera—. Agregar paginación real (skip/limit + total) en backend y frontend.

## Hecho (referencia rápida)

- Catálogo dental real de INSUMEDENT en la demo (1251 productos con stock real, 17 categorías).
- Flujo completo **picking → packing → despacho** clickeable, operable sin pistola lectora.
- Escáner con **soporte móvil**: cámara para escanear + teclado en pantalla al tocar.
- **"Volver a escanear"** para corregir líneas en picking y packing.
- **Retomar** tareas en curso: filas clickeables en Picking/Packing y "Continuar picking" en Pedidos.
- **Impresión de etiquetas** con código de barras EAN-13 escaneable (A4 o impresora térmica).
