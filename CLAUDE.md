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

## Levantar y probar

```bash
docker compose up --build                     # mongo + backend + worker + frontend
curl -X POST localhost:8000/api/v1/seed -H "X-Seed-Token: seed-me"

cd backend && pytest                          # suite completa, Mongo en memoria
cd frontend && npx tsc --noEmit               # verificación mínima tras tocar TS/TSX
```

`pytest` no necesita Mongo: `conftest.py` inyecta `mongomock_motor` y fuerza la
configuración por defecto, **ignorando el `.env` de quien ejecute**. Si agregas una
opción a `config.py` que los tests deban ver, ponla también en el fixture.

El frontend no tiene tests: la verificación es `tsc --noEmit` más mirar la pantalla.
Si tocas una pantalla y no la miras renderizada, **dilo explícitamente** en vez de
darla por buena.

## Convenciones

- **Todo en español**: commits, comentarios, documentación, UI y mensajes de error.
  Los asuntos de commit van en minúscula y **sin tildes**
  (`fix(inventario): hallazgos de la revision`), con el ámbito entre paréntesis
  (`ui`, `defontana`, `picking`, `inventario`, `despacho`, `docs`…).
- **Rama por trabajo** (`feat/...`, `fix/...`) y PR a `main`. No commitear en `main`.
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
- Las sincronizaciones automáticas están en un solo programador
  (`integrations/defontana/schedule.py`), con la última corrida por empresa en
  `scheduler_runs`. Cada nivel tiene su flag; ver la tabla del `ROADMAP.md`.
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

## Al terminar

Di qué verificaste y qué no. «Compila» no es «funciona»: si no corriste los tests o no
viste la pantalla, dilo. Es preferible un pendiente explícito a un supuesto silencioso.
