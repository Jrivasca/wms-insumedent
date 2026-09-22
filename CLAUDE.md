# CLAUDE.md — cómo trabajar en este repo

WMS multiempresa (SaaS) para Insumedent, integrado con el ERP **Defontana**.
El WMS manda en la **operación física de bodega**; Defontana manda en lo
**comercial, documental y contable**. La integración vive en una capa aparte y
**nunca** bloquea picking/packing.

**Antes de responder sobre el estado o los pendientes, lee `ROADMAP.md`**: es la
bitácora viva del proyecto (decisiones A.1–A.8, qué está hecho y qué falta). El
`README.md` cubre el stack y el arranque; `DEPLOY.md`, el droplet; `docs/entregables/`,
los análisis entregados al cliente.

Lo que lleva fecha caduca: verificarlo antes de confiar. Y hay una sección al final que
aplica **solo al equipo Windows**; si estás en Linux, saltala.

## Entornos

Hay **dos máquinas de desarrollo y un solo servidor**, y conviene no confundirlos.

| Dónde | Qué es | Estado al 2026-09-21 |
|---|---|---|
| **Linux** (`/home/jrivasca/Proyectos/CLAUDE/wms`) | La que **va a pasar a ser la principal** | Ya tiene git y Docker, y el stack corre entero (suite verde, `tsc` limpio). Le falta la base con datos del droplet. |
| **Windows** (`C:\Users\jrivasca\OneDrive\CLAUDE\wms\wms-insumedent`) | Hoy la única con Docker y la base con datos | Queda como respaldo. Tiene rarezas propias: ver el apéndice. |
| **Droplet** `root@137.184.137.130` | **Ambiente dev**, el único servidor | Es donde se despliega siempre. No hay producción todavía. |

El traslado a Linux conviene: ahí el Docker es nativo y **desaparecen todas las trampas
del apéndice**, que existen solo porque en Windows el repo vive dentro de OneDrive.

Corolario que no cambia: **lo que deba sobrevivir entre máquinas tiene que estar
versionado** (este archivo, `ROADMAP.md`, `docs/`). Ni el historial de conversaciones ni
la memoria de Claude viajan: se guardan por ruta absoluta, en la máquina.

### Mover el desarrollo al Linux

**Paso 0: instalar Docker. Hecho el 2026-09-21** — Docker 29.8.1 con `compose` v2, el usuario
ya en el grupo `docker`. Queda escrito el porqué de las decisiones, que es lo que sirve para
rehacerlo o para la próxima máquina.

Es **Ubuntu 26.04 "resolute"**; que sea Xubuntu no cambia nada, porque el sabor solo cambia el
escritorio y `/etc/os-release` sigue diciendo `ID=ubuntu` (importa porque el instalador de
Docker arma la línea del repositorio con `$VERSION_CODENAME`; en derivadas que reescriben ese
archivo, como Mint, eso falla). Se usa el **repositorio oficial de Docker**
(`docs.docker.com/engine/install/ubuntu/`), que al 2026-09-21 ya publica paquetes para
`resolute`. El motivo es tener las versiones al día y las mismas que el droplet: **no** que
Ubuntu no sirva — 26.04 trae `docker.io` 29.1.3 y `docker-compose-v2` 2.40.3, así que su
`docker compose` también es v2 y alcanzaría.

Después, `sudo usermod -aG docker $USER` y volver a entrar, para no depender de `sudo`.

**Ojo con las contraseñas:** `sudo` necesita un terminal, y una sesión de Claude por Remote
Control no lo tiene (`sudo: A terminal is required to authenticate`, ni siquiera con el
prefijo `!`). Esta máquina no tiene SSH levantado ni un helper `askpass`, así que la
instalación hay que correrla desde un terminal de verdad en el equipo.

**Lo mismo vale para la llave SSH del droplet**, y es fácil confundirlo con un problema de
permisos: `~/.ssh/id_ed25519` tiene passphrase, así que si el agente está vacío
(`ssh-add -l` → "The agent has no identities") cualquier `ssh root@137.184.137.130` muere con
**`Permission denied (publickey)`** — que suena a llave no autorizada, pero es solo que no hay
dónde escribir la passphrase. Se arregla desde un terminal de verdad:

```bash
ssh-add ~/.ssh/id_ed25519
```

El agente vive en un socket fijo de la sesión (`/run/user/1000/ssh-agent.socket`), así que la
sesión de Claude usa **el mismo** y hereda la llave sin más. Corre con `-t 8h`: la llave
**caduca a las 8 horas** y hay que repetir el `ssh-add`, que es por qué esto reaparece de un
día para otro.

Lo único que no está en git es **la base de datos**: vive en el volumen Docker
`mongo_data`. Conviene poblar el Linux desde **el droplet**, que es el dev real conectado
al Defontana de pruebas, y no desde la base local de Windows, que es un estado armado a
mano.

```bash
# en el Linux
ssh root@137.184.137.130 'docker exec wms_mongo mongodump --db wms --archive' > wms-dev.dump
docker compose up -d mongo
docker exec -i wms_mongo mongorestore --archive --drop < wms-dev.dump
```

**Aviso: las credenciales de Defontana del dump no van a descifrar.** La clave Fernet sale
de `ENCRYPTION_KEY`, y si está vacía se deriva del `JWT_SECRET` (`app/core/security.py`,
`_fernet()`); `deploy/deploy.sh` **le genera al droplet secretos propios**, distintos de los
locales. La salida correcta **no** es copiar la clave del droplet, sino **recargar las
credenciales desde la UI** (Configuración Defontana) en el ambiente local.

**Y falla en silencio, que es lo que cuesta reconocer** (verificado el 2026-09-21):
`decrypt_secret` atrapa el `InvalidToken` y **devuelve cadena vacía**
(`app/core/security.py:70`), así que no salta ninguna excepción. Lo que se ve es
`status` diciendo `"configured": true, "status": "connected"` —porque son los valores que
venían en el dump— y un `check` que responde `"Health check returned a non-OK response"`.
El único lugar donde aparece la causa es el log del backend, con la contraseña vacía a la
vista:

```
GET https://replapi.defontana.com/api/auth?client=...&user=INTEGRACION&password= "HTTP/1.1 400 BadRequest"
```

Parece un problema de credenciales o de red, y es de la clave local. De paso: **ese request
sale de verdad al ERP de pruebas**, porque el `.env` local trae `DEFONTANA_MOCK=false`.

Si el estado local de Windows importara (por ejemplo las filas de conciliación pendientes
de aprobación), sacar el respaldo **antes** de dejar esa máquina:

```bash
docker exec wms_mongo mongodump --db wms --archive=/tmp/wms.dump
docker cp wms_mongo:/tmp/wms.dump ./wms-local-respaldo.dump   # destino relativo a propósito
```

## Levantar y probar

El stack corre siempre en Docker, en cualquiera de las dos máquinas:

```bash
docker compose up --build                     # mongo + backend + worker + frontend
curl -X POST localhost:8000/api/v1/seed -H "X-Seed-Token: seed-me"

docker compose exec -T backend python -m pytest -q -p no:cacheprovider   # suite completa
```

`-p no:cacheprovider` evita que pytest intente escribir su caché en el montaje.

**Las dependencias viven dentro de los contenedores, no en el host.** El compose monta un
volumen anónimo en `/app/node_modules`, así que `frontend/node_modules` **existe pero está
vacío** — comprobar que la carpeta existe no basta, hay que mirar si tiene contenido. Por
eso, desde el host, `npx tsc --noEmit` y `npm run build` fallan con "tsc no se reconoce".
En el equipo Windows, además, `cd backend && pytest` tampoco corre: no hay entorno Python
fuera del contenedor. Para compilar (tsc + vite) hay que usar una copia con dependencias
fuera del repo y copiarle `frontend/src` encima.

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
  `origin/main`** (al 2026-09-21). El tronco real es `main`, así que `gh pr create`, la UI
  de GitHub y un `git clone` sin `-b main` te dejan en la base equivocada. Siempre salir de
  `origin/main` y apuntar explícito:
  ```bash
  git fetch origin && git switch -c <rama> origin/main
  gh pr create --base main
  ```
  (Vale arreglarlo de raíz en *Settings → General → Default branch*.)
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

- **Quién manda sobre el stock** (la decisión que gana ante cualquier duda de diseño):
  **Defontana es la fuente de verdad de las cantidades; el WMS, de las ubicaciones.**
  Nada de lo que el WMS hace con ubicaciones viaja al ERP.
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
  `DEFONTANA_INVENTORY_SYNC_ENABLED` apagado. El **centro de negocio** (A.2) ya está confirmado
  —`EMPNEGVTAVTA000`, probado por escritura contra `Inventory/Insert` el 2026-09-21— así que lo
  que traba el envío de inventario es el corte de bodega, no A.2. Para las **guías** el mapeo de
  `Order/DispatchOrder` **ya está construido** (`build_dispatch_order`, detrás de
  `erp_sync_enabled`); faltan confirmar dos valores del `dispatchInfo` (`transactionType` y
  `originStorageInfo.motive`, ver B.1 en `ROADMAP.md`). No lo enciendas sin confirmarlos.
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
- **La conciliación no consulta al ERP: lee la colección `erp_stock` de la propia base**
  (`erp_reconcile_service._rows`). O sea que **no la frenan las credenciales**: en un local
  restaurado desde el droplet tiene datos suficientes para ajustar stock sola. Lo único que
  la detiene es que la foto tenga más de 12 h (`MAX_SNAPSHOT_AGE` en
  `defontana_scheduler.py`). Al restaurar un dump viejo eso alcanza; pero apenas se recargan
  las credenciales, la sincronización de stock de las 03:30 deja foto fresca y la
  conciliación de las 04:30 **se ejecuta**. Si el local no se va a usar para eso, dejarla en
  `false`.
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

Se puede desplegar **desde cualquiera de las dos máquinas**: el procedimiento sale de
`origin/main` y el respaldo y el `deploy.sh` corren dentro del droplet. Lo único que hace
falta es tener la llave SSH autorizada allá.

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
- **A.2, centro de negocio**: **confirmado (2026-09-21)** — `EMPNEGVTAVTA000` (VENTAS), verificado
  en el ERP web (Configuración → General → Centro de Negocios) y probado por escritura contra
  `Inventory/Insert`. Ya no bloquea; el envío de inventario sigue apagado por el corte, no por A.2.
- **B.1, mapeo de `Order/DispatchOrder`**: **mapeo construido** (2026-09-22); faltan confirmar
  `transactionType` y `originStorageInfo.motive`, que exigen emitir una guía de prueba (consume
  folio, no se borra) o preguntar a Defontana. El envío queda apagado (`erp_sync_enabled`) hasta
  eso, así que por ahora **ninguna guía viaja al ERP**.

## Intentado y descartado (no repetir)

- **Deploy por GitHub Actions.** Escrito, nunca ejecutado, sin secrets. Se hace por SSH.
- **Apilar un PR sobre otro en revisión.** Dejó `main` a medias y costó un PR extra.
- **`*.svg` como `binary` en `.gitattributes`.** Dejaba el archivo eternamente "modificado"
  en checkouts de Windows por el CRLF. Se volvió a `text eol=lf`.
- **`npm run build` / `npx tsc` en `frontend/` del host.** `node_modules` está vacío.
- **Comparar fechas dentro de una agregación de Mongo.** Pasa en el droplet, revienta en tests.
- **Crear productos en Defontana vía API.** `Sale/SaveProduct` es del módulo Ventas, no
  contratado. De ahí el importador de Excel (A.8).
- **Encender la conciliación diaria "para probar".** Corre al instante y ajusta stock.
- **Copiar la clave de cifrado del droplet** para poder leer sus credenciales en local. Se
  recargan desde la UI y listo (ver "Mover el desarrollo al Linux").
- En el equipo Windows: **`git update-index --refresh`** para limpiar los archivos fantasma
  (no persiste) y **pinnear un archivo en OneDrive** para que no se deshidrate (`ROADMAP.md`
  ya estaba pinneado y lo evacuó igual). Ver el apéndice.

## Al terminar

Di qué verificaste y qué no. «Compila» no es «funciona»: si no corriste los tests o no
viste la pantalla, dilo. Es preferible un pendiente explícito a un supuesto silencioso.

---

## Apéndice — rarezas del equipo Windows (OneDrive)

**Esto aplica solo en Windows**, porque ahí el repo vive dentro de OneDrive
(`C:\Users\jrivasca\OneDrive\CLAUDE\wms\wms-insumedent`). En Linux no pasa nada de esto.

**1. `git status` miente: decenas de archivos salen como ` M` sin tener ningún cambio.**
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
watcher incluso muere con "os error 5"). No quitarlo — el flag es inocuo en Linux.
