# WMS Defontana — Warehouse Management System

WMS SaaS multiempresa para gestionar inventario, ubicaciones, picking, packing,
despacho y recepción, con sincronización a ERP. El primer ERP integrado es
**Defontana**, mediante una capa de conectores preparada para soportar otros ERP
en el futuro.

El WMS es el sistema maestro de la **operación física de bodega**; Defontana se
mantiene como sistema maestro **comercial, documental y contable**. La integración
ERP vive en una capa separada y nunca bloquea la operación de picking/packing.

## Stack

| Capa        | Tecnología |
|-------------|-----------|
| Backend     | Python 3.12 · FastAPI · Uvicorn · Pydantic v2 · Motor (MongoDB async) · JWT · Passlib/Bcrypt · HTTPX |
| Base de datos | MongoDB 7 |
| Frontend    | React · Vite · TypeScript · TailwindCSS · PWA · `@zxing/browser` (escaneo por cámara) + lector HID |
| Worker      | Proceso Python que consume `sync_jobs` (cola sobre Mongo, sin Celery) |
| Infra       | Docker · Docker Compose · variables `.env` |

## Arquitectura (monorepo)

```
wms-insumedent/
  docker-compose.yml
  .env.example
  backend/            FastAPI + Motor + worker
    app/
      core/           config, database, security, logging, utils
      models/         enums y constantes de dominio + nombres de colecciones
      schemas/        modelos Pydantic de request/response
      api/routes/     endpoints REST /api/v1
      services/       lógica de negocio (auth, inventory, picking, packing, ...)
      integrations/   ERPConnector + Defontana (client, token_manager, mapper, syncs)
      workers/        sync_worker.py
      seed.py         seed demo
      tests/          pruebas de flujo (pytest)
  frontend/           React + Vite PWA (modo supervisor y modo operario)
```

## Puesta en marcha (local con Docker)

```bash
cp .env.example .env
docker compose up --build
```

Servicios y URLs esperadas:

| Servicio  | URL |
|-----------|-----|
| Frontend  | http://localhost:5173 |
| Backend   | http://localhost:8000 |
| Swagger   | http://localhost:8000/docs |
| MongoDB   | mongodb://localhost:27017 |

### Cargar datos demo (seed)

El seed es un endpoint protegido. Tras levantar los servicios:

```bash
curl -X POST http://localhost:8000/api/v1/seed \
  -H "X-Seed-Token: seed-me"
```

Crea:

- **Tenant:** Demo Company
- **Usuario admin:** `admin@demo.cl` / `admin123`
- **Bodega:** BODEGA CENTRAL con ubicaciones `A-01-01`, `A-01-02`, `STAGING`, `PACKING`, `DISPATCH`, `QUARANTINE`
- **Productos:** SKU001 (780000000001), SKU002 (780000000002), SKU003 (780000000003) con stock inicial
- **Pedido demo:** 1001 (2 líneas)

Luego inicia sesión en http://localhost:5173 con el usuario admin.

## Integración Defontana: modo mock y modo real

La integración se controla con `DEFONTANA_MOCK`:

- `DEFONTANA_MOCK=true` (por defecto): el conector devuelve **datos simulados**
  para productos, bodegas, pedidos y despacho. Toda respuesta simulada queda
  marcada con `"mock": true`, de modo que un éxito simulado nunca se confunde con
  uno real.
- `DEFONTANA_MOCK=false`: el conector consume los endpoints reales de Defontana
  vía HTTPX usando las credenciales configuradas por tenant (cifradas en base de
  datos). El `TokenManager` mantiene un token Bearer centralizado por tenant, lo
  reutiliza hasta que vence y lo renueva una sola vez ante un 401.

Las credenciales se configuran desde **Configuración Defontana** en el frontend o
vía `POST /api/v1/integrations/defontana/configure`. Nunca se guardan en texto
plano ni se exponen al frontend.

Endpoints Defontana implementados inicialmente: `auth`, `auth/emailLogin`,
`Auth/check`, `Company`, `sale/GetProducts`, `sale/GetSimpleProducts`,
`sale/GetProductsPOSByBarCode`, `sale/GetProductsPOSByCode`, `sale/GetStorages`,
`Order/List`, `Order/DispatchOrder`, `Inventory/Insert`,
`Inventory/GetDocumentByExternalDocumentID`.

## Reglas de negocio clave

- **Picking:** una tarea se asigna a un usuario; el operario debe escanear antes de
  confirmar cantidad; un código que no corresponde al producto esperado se rechaza;
  se puede marcar faltante con motivo obligatorio; no se cierra con líneas pendientes
  salvo que un supervisor autorice picking parcial. Cada escaneo queda registrado con
  usuario, fecha y dispositivo.
- **Packing:** solo inicia con el picking cerrado; se re-escanea; si hay diferencia
  con el picking la tarea queda `observed` y solo un supervisor la aprueba; al cerrar,
  el pedido queda `ready_to_dispatch`.
- **Despacho:** solo se confirma si el pedido está `ready_to_dispatch`; crea un
  `sync_job` tipo `dispatch_order` que el worker envía a Defontana; no se permite
  doble despacho.
- **Inventario:** toda modificación de stock crea un movimiento en
  `inventory_movements` (nunca se actualiza stock sin movimiento); sin stock negativo
  salvo configuración explícita (`ALLOW_NEGATIVE_STOCK`); los ajustes los aprueba un
  supervisor; los documentos de inventario llevan `externalDocumentID` y se consulta
  su existencia antes de reintentar.

## Seguridad

Login interno JWT, hash bcrypt, middleware de autenticación, roles y permisos
(`admin`, `supervisor`, `picker`, `packer`, `receiver`, `auditor`), CORS
configurable, cifrado de credenciales Defontana, y sanitización de secretos en
logs y auditoría. Las acciones críticas quedan en `audit_logs`.

## Worker de sincronización

`sync_worker.py` usa MongoDB como cola simple: toma jobs `pending`/`retrying`,
los marca `processing`, ejecuta la operación, y ante fallo incrementa `attempts`
con backoff exponencial hasta `max_attempts` (luego `failed`). Tipos:
`sync_products`, `sync_warehouses`, `sync_orders`, `dispatch_order`,
`create_inventory_document`.

## Desarrollo y pruebas del backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest            # pruebas de flujo end-to-end con Mongo en memoria
```

Las pruebas cubren: seed idempotente, login, búsqueda por código de barra, flujo
completo picking → packing → despacho → worker, bloqueo de doble despacho y sync
de productos en modo mock.

## Variables de entorno (`.env`)

Ver `.env.example`. Las más relevantes:

| Variable | Descripción |
|----------|-------------|
| `MONGODB_URI` / `MONGODB_DB` | conexión Mongo |
| `JWT_SECRET` / `JWT_EXPIRE_MINUTES` | firma y expiración de tokens |
| `ENCRYPTION_KEY` | clave Fernet para cifrar credenciales (si vacía, se deriva del `JWT_SECRET`) |
| `SEED_TOKEN` | token requerido por el endpoint de seed |
| `DEFONTANA_MOCK` | `true`/`false` |
| `DEFONTANA_ENV` / `*_BASE_URL` | entorno y URLs de Defontana |
| `CORS_ORIGINS` | orígenes permitidos (coma-separados) |

## Nota

Esta es una **primera base funcional del WMS**: simple pero extensible. El backend
expone Swagger en `/docs`, el frontend es una PWA responsiva con modo supervisor y
modo operario optimizado para móvil/pistola, y la integración Defontana queda lista
en modo mock y modo real.
