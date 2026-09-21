# CLAUDE.md — cómo trabajar en este repo

WMS multiempresa (SaaS) para Insumedent, integrado con el ERP **Defontana**.
El WMS manda en la **operación física de bodega**; Defontana manda en lo
**comercial, documental y contable**. La integración vive en una capa aparte y
**nunca** bloquea picking/packing.

**Antes de responder sobre el estado o los pendientes, lee `ROADMAP.md`**: es la
bitácora viva del proyecto (decisiones A.1–A.8, qué está hecho y qué falta). El
`README.md` cubre el stack y el arranque; `DEPLOY.md`, el droplet; `docs/entregables/`,
los análisis entregados al cliente.

## Entornos (importante)

El desarrollo real se hace en un **equipo Windows** (`C:/Users/jrivasca/.../wms-insumedent`),
que es el que tiene Docker y la base con datos. La carpeta en Linux
(`/home/jrivasca/Proyectos/CLAUDE/wms`) es una **copia del repo**: sirve para leer,
planificar y escribir código, pero **no tiene docker ni mongod**, así que ahí no se
levanta el stack ni corren los tests sin preparar antes un venv.

Corolario: **lo que deba sobrevivir entre máquinas tiene que estar versionado**
(este archivo, `ROADMAP.md`, `docs/`). El historial de conversaciones no viaja.

### Trampas del equipo Windows (la carpeta está dentro de OneDrive)

La ruta real es `C:\Users\jrivasca\OneDrive\CLAUDE\wms\wms-insumedent` — **dentro de
OneDrive**, y de ahí vienen casi todas las rarezas de esta máquina.

**1. `git status` miente: ~48 archivos salen como ` M` sin tener ningún cambio.**
`git diff` sale vacío, el hash del archivo en disco es idéntico al blob del índice
(`git hash-object <f>` == `git ls-files -s <f>`), y `git ls-files --eol` da `i/lf w/lf`
en todos, así que **no es un problema de fin de línea**. Es la caché de `stat` del índice
envejecida porque OneDrive reescribe los mtime al sincronizar; `git update-index
--refresh` los marca "needs update" pero no persiste.

> Por eso: para saber si hay cambios reales usar **`git diff --stat`**, no `git status`,
> y **commitear con rutas explícitas** (`git add CLAUDE.md`). No perseguir esos archivos.

**2. OneDrive puede dejar un archivo rastreado ILEGIBLE.** Pasó el 2026-09-21 con
`ROADMAP.md`: OneDrive lo deshidrató a placeholder "solo en la nube" justo después de
editarlo y después **no pudo rehidratarlo** ("el proveedor de sincronización en la nube no
pudo validar los datos descargados"). Los cambios recién escritos se perdieron.

Se ve así, y ninguno de los síntomas menciona OneDrive:

- `git diff` / `git add` fallan con `fatal: mmap failed: Invalid argument` o
  `error: read error while indexing <archivo>: Invalid argument`.
- `head`, `cat`, `wc -l` dan **`Permission denied`**, pero `wc -c` sí reporta tamaño
  (el tamaño es metadato; el contenido no está en disco).

Diagnóstico y recuperación:

```bash
attrib ROADMAP.md                          # "A  O  P" -> la O es Offline = placeholder
rm -f ROADMAP.md && git checkout HEAD -- ROADMAP.md
```

Y después **reaplicar los cambios y commitear de inmediato**: mientras el cambio solo vive
en el archivo del disco, OneDrive lo puede volver a evacuar. Si un comando de git falla con
`mmap failed` o `Invalid argument`, **mirar `attrib` antes de sospechar del repo**.
Pinnear no sirve: el archivo ya estaba pinneado (`P`) y lo evacuó igual.

**3. Git Bash reescribe rutas.** `docker exec ... /tmp/x` se convierte en una ruta de
Windows. Usar `export MSYS_NO_PATHCONV=1`, y destinos relativos en `docker cp`.

**4. Los montajes de Windows/OneDrive no emiten eventos de archivo**, por eso el compose
fuerza `WATCHFILES_FORCE_POLLING`; sin eso `uvicorn --reload` no ve los cambios (su
watcher incluso muere con "os error 5"). No quitarlo.

## Levantar y probar

```bash
docker compose up --build                     # mongo + backend + worker + frontend
curl -X POST localhost:8000/api/v1/seed -H "X-Seed-Token: seed-me"

# Suite completa. En el equipo Windows va SIEMPRE por el contenedor:
docker compose exec -T backend python -m pytest -q -p no:cacheprovider
```

**En el equipo Windows, `cd backend && pytest` no funciona**: no hay entorno Python
fuera del contenedor. Tampoco `cd frontend && npx tsc --noEmit`: `frontend/node_modules`
**existe pero está vacío**, porque el compose monta un volumen anónimo en
`/app/node_modules` y las dependencias viven dentro del contenedor. Falla con
"tsc no se reconoce". Comprobar que la carpeta existe no basta — hay que mirar si tiene
contenido. Para compilar (tsc + vite) hay que usar una copia con dependencias fuera del
repo y copiarle `frontend/src` encima.

`-p no:cacheprovider` evita que pytest intente escribir su caché en el montaje.

`pytest` no necesita Mongo: `conftest.py` inyecta `mongomock_motor` y fuerza la
configuración por defecto, **ignorando el `.env` de quien ejecute**. Si agregas una
opción a `config.py` que los tests deban ver, ponla también en el fixture.

Ojo con las fechas en los tests: **mongomock guarda las fechas con zona y Mongo real las
devuelve sin zona**, así que comparar fechas *dentro de una agregación* pasa en el
droplet y revienta en los tests. Clasificar en Python, con una sola función compartida.

El frontend no tiene tests: la verificación es `tsc --noEmit` más mirar la pantalla.
Si tocas una pantalla y no la miras renderizada, **dilo explícitamente** en vez de
darla por buena.

El worker **no** se recarga solo (el backend sí, con HMR). Para que tome un `.env` nuevo:
`docker compose up -d --force-recreate worker backend`.

## Convenciones

- **Todo en español**: commits, comentarios, documentación, UI y mensajes de error.
  Los asuntos de commit van en minúscula y **sin tildes**
  (`fix(inventario): hallazgos de la revision`), con el ámbito entre paréntesis
  (`ui`, `defontana`, `picking`, `inventario`, `despacho`, `docs`…).
- **Rama por trabajo** (`feat/...`, `fix/...`) y PR a `main`. No commitear en `main`.
- **Cuidado: la rama por defecto en GitHub no es `main`.** `origin/HEAD` apunta a
  `claude/crea-development-definitions-8cu566`, que está **9 commits atrás de
  `origin/main`** (al 2026-09-21). El tronco real es `main`, así que `gh pr create` y la UI
  de GitHub proponen la base equivocada. Siempre salir de `origin/main` y apuntar explícito:
  ```bash
  git fetch origin && git switch -c <rama> origin/main
  gh pr create --base main
  ```
- **Nunca apilar un PR sobre otro en revisión**, aunque el trabajo continúe algo que aún no
  está en `main`. El 2026-09-20 el PR #22 se basó en la rama del #21; al mergearse el #21
  primero, el #22 quedó mergeado **dentro de una rama de trabajo y no en `main`**, que quedó
  a medias justo antes de un despliegue, y hubo que abrir el #23 solo para reubicar commits
  ya aprobados. Si el trabajo depende de algo que no está en `main`: decirlo en el PR y
  esperar, o rebasar cuando el anterior se mergee.
- Los comentarios explican **por qué**, no qué hace la línea. El repo está lleno de
  ejemplos (mira `tenant_db.py` o `.gitattributes`); manténlo así.
- **Finales de línea LF** forzados por `.gitattributes`: el deploy es Linux y un `\r`
  en un shebang rompe el script en el droplet. No lo cambies desde Windows.
- Al cerrar un trabajo, **actualiza `ROADMAP.md`** en el mismo PR: es el único lugar
  donde el estado queda registrado entre sesiones y entre máquinas.

## Invariantes de negocio (no romper)

- **Stock**: ninguna modificación de saldo sin su movimiento en `inventory_movements`.
  Sin stock negativo salvo `ALLOW_NEGATIVE_STOCK`. Los ajustes los aprueba un supervisor.
- **Multi-tenant**: los servicios acceden a datos con `tenant_db(tenant_id)`
  (`app/core/tenant_db.py`), que inyecta y verifica `tenant_id` solo. No uses
  `get_database()` directo salvo en los casos ya exceptuados y documentados ahí
  (login, `get_current_user`, poll global del worker, `seed.py`).
- **Picking/packing**: se escanea antes de confirmar; un código que no corresponde se
  rechaza; no se cierra con líneas pendientes sin autorización de supervisor; una
  diferencia en packing deja la tarea `observed` hasta que un supervisor la apruebe.
- **Despacho**: solo desde `ready_to_dispatch`, y nunca dos veces sobre lo mismo.
- **Secretos**: las credenciales de Defontana van cifradas (Fernet) y **nunca** se
  exponen al frontend ni se escriben en logs o auditoría.

## Integración Defontana

- `DEFONTANA_MOCK=true` devuelve datos simulados, siempre marcados con `"mock": true`
  para que un éxito simulado no se confunda con uno real. **Mantén esa marca.**
- **Hoy el WMS lee del ERP pero no le escribe**: `ERP_SYNC_ENABLED=false` y
  `DEFONTANA_INVENTORY_SYNC_ENABLED` apagado, porque falta que Insumedent confirme el
  **centro de negocio** (decisión A.2) y el mapeo de `dispatchInfo` para las guías.
  No los enciendas sin esas definiciones.
- Las sincronizaciones automáticas están en un solo programador,
  **`app/workers/defontana_scheduler.py`** (corre en el worker), con la última corrida por
  empresa en `scheduler_runs`. Cada nivel tiene su flag; ver la tabla del `ROADMAP.md`.
  (`integrations/defontana/schedule.py` es otra cosa: solo los helpers de hora local y
  ventana horaria.)
- **La conciliación diaria está apagada a propósito en el droplet**
  (`DEFONTANA_RECONCILE_ENABLED=false`): al encenderla **corre de inmediato y ajusta stock
  sin revisión previa**. Se enciende recién cuando la bodega esté ubicada. No prenderla
  "para ver qué hace". En el `.env` **local** está en `true`; son entornos distintos, y el
  que puede romper datos es el del droplet.
- **Escribir al ERP de pruebas** (`replapi.defontana.com`) está autorizado **solo si cada
  documento creado se borra después y se verifica**. Dos detalles que cuestan encontrar: al
  borrar, el **folio va como entero** (`Folio=884`, no `884.0`), y un `GetDocument` de un
  documento inexistente devuelve `stockLoadOutputData: null`, que **no es un error**.
- Las dudas de la API van por el canal de Slack `integracion-insumedent`, donde responde
  **Luis López** (Defontana). **Los mensajes los escribe el dueño del proyecto; Claude solo
  los redacta.** Nunca pegar la contraseña de Defontana en el chat.
- Módulos contratados: **Pedidos, Inventario y Guías de Despacho**. Ventas (`Sale/*`)
  y Contabilidad **no**: si una solución necesita uno de esos endpoints, no es viable
  y hay que decirlo en vez de codificarla.
- El catálogo de productos se carga por **importador de Excel** (decisión A.8); no se
  crean productos automáticamente desde el ERP.

## Frontend

- Tokens visuales en `tailwind.config.js`, clases de componente en `src/index.css`,
  traducción de estados en `src/lib/status.ts`. **La traducción es solo de vista: los
  valores internos que viajan al backend no cambian.**
- Feature flags en `src/config.ts`.
- Escritorio = tabla, móvil = tarjetas. Los códigos (SKU, ubicación, folio) en
  monoespaciada. Las confirmaciones explican la consecuencia; nada de `window.confirm`.
- **No tocar el marcado de las etiquetas impresas** (50×30 mm, saltos de página, QR de
  260 px): está calibrado para la impresora térmica y no se puede verificar sin imprimir.

## Despliegue: cómo se hace de verdad

`DEPLOY.md` describe una instalación limpia y genérica. Lo que se hace realmente es esto,
y en dos puntos **contradice** a `DEPLOY.md`.

- El WMS vive en **https://wms-dev.selarix.cl**, droplet **`root@137.184.137.130`**, código
  en **`/opt/wms-insumedent`**. Es **ambiente dev, no producción**, aunque esté en línea.
- El droplet está **compartido con otros proyectos**: hay un **Caddy propio del droplet**
  (fuera de este stack) que enruta hacia `127.0.0.1:8080`. Es el "Caso B" de `DEPLOY.md`: el
  WMS **no** toma 80/443.
- Apunta al **Defontana de pruebas**, con credenciales cargadas desde la UI. El login sigue
  siendo el demo (`admin@demo.cl`).
- **`DEPLOY.md` llama "recomendado" al deploy por GitHub Actions: no se usa.** El workflow
  existe pero **nunca se ha ejecutado y no tiene los secrets cargados**. Todos los
  despliegues han sido por SSH desde la sesión.
- **`DEPLOY.md` dice `git checkout claude/crea-development-definitions-8cu566`: está
  desactualizado.** Se despliega desde `main`.

**El procedimiento, en orden:**

**1. Respaldo primero, siempre.** Nunca desplegar sin esto.

```bash
tar czf /root/wms-backups/wms-$(date +%F-%H%M).tar.gz --warning=no-file-changed /opt/wms-insumedent
docker exec wms_mongo mongodump --db wms --archive=/tmp/wms.dump
```

`--warning=no-file-changed` **no es opcional**: sin esa bandera, un archivo de
`inbound/procesados` que cambia durante el empaquetado hace que `tar` **aborte** y el
respaldo quede a medias. Validar el dump con **`mongorestore --dryRun`** antes de darlo por
bueno. Todo queda en `/root/wms-backups/`.

**2. Antes de desplegar, comparar `origin/main` con la rama que se probó:**
`git diff --stat origin/main <rama>`. Si no sale vacío, `main` **no tiene** lo que se probó
(esto ya pasó, ver el incidente de los PRs #21–#23 en Convenciones).

**3. Desplegar desde `origin/main`:**

```bash
git archive --format=tar origin/main | gzip | \
  ssh root@137.184.137.130 'tar xzf - -C /opt/wms-insumedent && cd /opt/wms-insumedent && bash ./deploy/deploy.sh'
```

**4. Verificar los tres, no solo el primero:** que `/health` responda; que las **rutas nuevas
devuelvan 401 y no 404** (401 = existe y pide auth, o sea el código llegó; 404 = no llegó); y
los logs de **`wms_backend` y `wms_worker`** — el worker falla en silencio, si no se miran sus
logs un job roto no se nota.

**Reglas del droplet:** el `.env` se edita **clave por clave con `sed`**, nunca se vuelca
entero. **No tocar producción sin permiso.** Leer la base del droplet puede quedar bloqueado
por el clasificador de permisos: si pasa, pedir autorización en vez de insistir con variantes
del comando.

**Encendido al 2026-09-20:** sincronización de pedidos (lun–vie 08:00–19:00) y de stock
(03:30). Conciliación diaria **apagada** (ver Integración Defontana).

## Estado real de la puesta en marcha (2026-09-20)

El flujo está construido y desplegado en dev, pero **la bodega todavía no opera con el WMS**.
El procedimiento del corte está en `docs/entregables/Puesta-en-marcha-primera-vez.md`. Lo que
falta depende de terceros, no de código:

- **181 productos que Defontana tiene y el WMS no**
  (`docs/entregables/Productos-Defontana-no-en-WMS-2026-09-19.csv`). Quedan **bloqueados en la
  conciliación**: su stock no entra, así que no se puede ubicar ni pickear. **Es el primer
  paso.** Tres tienen stock en camino (102152 CARISTOP 720, DNITTRESM y DNITTRESS, 500 c/u).
- **282 filas de conciliación esperando aprobación humana** (más del 95 % del volumen).
  Aprobarlas una por una es inviable: probablemente haga falta una **aprobación en bloque**
  antes del corte.
- **A.2, centro de negocio**: pendiente de que Insumedent lo confirme. Mientras tanto el envío
  de inventario al ERP sigue apagado.
- **B.1, mapeo de `Order/DispatchOrder`**: pendiente de Defontana. Sin eso **ninguna guía viaja
  al ERP**, ni la primera ni la del pendiente.

## Intentado y descartado (no repetir)

- **Deploy por GitHub Actions.** Escrito, nunca ejecutado, sin secrets. Se hace por SSH.
- **Apilar un PR sobre otro en revisión.** Dejó `main` a medias y costó un PR extra.
- **`*.svg` como `binary` en `.gitattributes`.** Dejaba el archivo eternamente "modificado"
  en checkouts de Windows por el CRLF. Se volvió a `text eol=lf`.
- **`npm run build` / `npx tsc` en `frontend/` del host.** `node_modules` está vacío.
- **`git update-index --refresh` para limpiar los archivos fantasma.** No persiste.
- **Pinnear un archivo en OneDrive para que no se deshidrate.** `ROADMAP.md` ya estaba
  pinneado y lo evacuó igual, y encima no pudo devolverlo.
- **Comparar fechas dentro de una agregación de Mongo.** Pasa en el droplet, revienta en tests.
- **Crear productos en Defontana vía API.** `Sale/SaveProduct` es del módulo Ventas, no
  contratado. De ahí el importador de Excel (A.8).
- **Encender la conciliación diaria "para probar".** Corre al instante y ajusta stock.

## Al terminar

Di qué verificaste y qué no. «Compila» no es «funciona»: si no corriste los tests o no
viste la pantalla, dilo. Es preferible un pendiente explícito a un supuesto silencioso.
