# Etiquetas en la Zebra ZD220 (3 columnas, 30 × 10 mm)

Perfil «Zebra ZD220 — 3 columnas — 30 × 10 mm» de la pantalla **Etiquetas** (`/labels`,
supervisor o administrador). Los formatos de 50 × 30 mm de siempre no cambian.

## Cómo imprime

El WMS corre en la nube y **no ve el USB** del computador. Hay dos caminos, los dos sin
instalar nada:

1. **Navegador → controlador de Windows** (botón *Imprimir*). La página mide exactamente
   *ancho del papel × alto de etiqueta* (`@page`, margen 0) y **cada fila de 3 es una
   página**. La app se oculta entera al imprimir; solo salen las filas.
2. **Archivo ZPL** (botón *ZPL*). Las mismas posiciones, en puntos de 203 dpi, sin pasar
   por el navegador ni por el controlador: es el camino exacto. Se envía a la impresora
   compartida en Windows:

   ```bat
   copy /b etiquetas-zd220.zpl \\NOMBRE-PC\ZD220
   ```

   (`ZD220` = nombre del recurso compartido; desde otro PC de la red, el mismo comando.)

Imprimir **sin diálogo** desde el navegador exigiría un programa local que reciba el ZPL
(Zebra Browser Print o similar). No está incluido: requiere instalarlo en cada PC.

## Configurar Windows (controlador «ZDesigner ZD220-203dpi ZPL»)

- Preferencias de impresión → papel personalizado **95 × 10 mm** (o lo que se mida),
  vertical, **etiquetas con espacios** (gap), **térmica directa**, desplazamientos 0.
- Calibrar el sensor con el rollo puesto (botón de la impresora o *Herramientas → Calibrar*).
- En el diálogo de Chrome/Edge: esa impresora, **Escala 100 %** (nunca «Ajustar»),
  **Márgenes: Ninguno**, sin *Encabezados y pies de página*. Con margen 0 Chrome no tiene
  dónde ponerlos (verificado), pero conviene desmarcarlos igual.

## Perfil

| Campo | Inicial | Estado |
|---|---|---|
| Ancho del papel | 95 mm | **Provisional** (regla) |
| Etiqueta | 30 × 10 mm | Dato del rollo |
| Columnas | 3 | Dato del rollo |
| Margen izq. / der., separación entre columnas | 1,25 mm c/u | **Sin medir**: reparte parejo los 5 mm sobrantes |
| Separación entre filas | 0 | Sin medir; solo informativa (el avance lo detecta la impresora) |
| Ajuste horizontal / vertical | 0 | Calibración fina |

La pantalla valida que márgenes + etiquetas + separaciones quepan en el ancho del papel
(error si no caben, aviso si sobran más de 0,5 mm) y que la plantilla quepa en la etiqueta.
El perfil se guarda en el navegador de cada PC (la calibración es de cada equipo).

## Contenido de la etiqueta

Solo **EAN-13 + SKU** (el nombre no cabe en 30 × 10 mm):

- Módulo de **0,25 mm = 2 puntos** a 203 dpi: código de 23,75 mm, centrado, con **3,125 mm
  de zona de silencio a cada lado** (GS1 pide 2,75 mm a la izquierda y 1,75 mm a la derecha).
  Con 1 punto por módulo el cabezal térmico no resuelve bien las barras; con 3, no cabe.
- Barras de 6,125 mm de alto (EAN-13 truncado: no cumple el alto nominal de GS1 para punto
  de venta; para lectura interna con pistola es lo habitual, pero **hay que probarlo**).
- SKU en monoespaciada de 2,1 mm, hasta 22 caracteres (el más largo del catálogo tiene 22).
- No se imprime (y se avisa por qué): sin código, código que no es EAN-13 válido (incluye el
  dígito verificador) o SKU que no cabe. Nunca se achica ni se trunca para forzarlo.

## Prueba física (pendiente)

1. **Alineación**: *Prueba de alineación* imprime una fila con IZQUIERDA / CENTRO / DERECHA,
   cada una en un marco 0,5 mm adentro de su etiqueta. Si un marco pisa el borde o el
   espacio entre etiquetas, corregir la medida (márgenes, separación, ancho del papel) o, si
   es un corrimiento parejo, el ajuste fino. Repetir hasta que los tres queden dentro.
2. **Avance de una fila**: imprimir 4 etiquetas (2 filas). La segunda debe empezar en la
   segunda fila de etiquetas, sin saltarse una ni montarse. Si avanza de más, revisar el
   alto del papel del controlador y recalibrar el sensor.
3. **Lectura**: escanear cada columna con la pistola de bodega y comparar con el código
   que muestra Productos. Probar también el ZPL (`Prueba en ZPL` y un lote).

## Validado sin impresora (2026-10-01)

- Chrome imprime a PDF: 1, 2, 3, 4 y 7 etiquetas → 1, 1, 1, 2 y 3 páginas de
  ~95 × 10 mm, sin página en blanco al final, sin la app, en orden; la última fila con
  huecos en su lugar.
- Rasterizado a 203 dpi: 30 barras por código, anchos múltiplos de 2 puntos, posiciones a
  ±1 punto de las del ZPL. Decodificados por software (ZXing) con el valor correcto.
- **No** validado con escáner ni en la ZD220 real.

## Limitaciones

- **10 mm de alto es el límite**: con menos de ~8 mm las barras quedan bajo 4 mm y la
  plantilla se rechaza. Cualquier deriva vertical de la impresora (±0,5–1 mm es común en
  etiquetas tan bajas) se come el margen de 0,75 mm arriba y abajo: el ajuste vertical
  compensa una deriva pareja, no una irregular.
- Chrome redondea el tamaño de página del PDF (95 mm → 94,91 mm). Al rasterizar eso dejó
  **una barra de 1 punto** por código en la prueba a PDF. Con la impresora real el resultado
  depende del controlador; si la lectura falla, usar el **ZPL**, que pone cada barra en
  2 puntos exactos.
- Solo códigos EAN-13 (hoy todo el catálogo: internos con prefijo 20). Un código Code 128
  de 13 dígitos ocupa más que un EAN-13 y no cabe con sus zonas de silencio en 30 mm.
