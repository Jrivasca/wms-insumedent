# Despliegue en un droplet de DigitalOcean

Guía para instalar el WMS en un droplet Ubuntu, accesible por **IP/HTTP**, con el
reverse proxy (Caddy) ya preparado para activar **HTTPS con un dominio** después
sin reconstruir nada.

## Arquitectura del despliegue

Un solo droplet corre todo con Docker Compose (`docker-compose.prod.yml`):

```
            ┌─────────────── droplet ───────────────┐
Internet ──▶│  Caddy :80/:443                        │
            │    ├─ /api/*, /health, /docs ─▶ backend (uvicorn :8000)
            │    └─ /*                      ─▶ frontend (nginx, build estático)
            │  worker  ─┐                            │
            │  backend ─┴─▶ mongo:27017 (interno)    │
            └───────────────────────────────────────┘
```

Solo Caddy publica puertos. MongoDB, backend, worker y frontend quedan en la red
interna. El frontend se sirve **estático** y llama a la API en el **mismo origen**
(`/api/v1`), por lo que añadir un dominio luego es solo un cambio de variable.

## Coexistencia con otros proyectos en el droplet

El stack no toca tus otros proyectos: MongoDB no expone puertos, los volúmenes y
la red van *namespaced* por proyecto, y Docker ya instalado se reutiliza. El único
punto de choque posible son los **puertos 80/443**.

**Caso A — 80/443 están libres:** no cambies nada. El WMS toma 80/443 y queda en
`http://IP/` (y HTTPS automático al poner un dominio en `SITE_ADDRESS`).

**Caso B — ya tienes un reverse proxy (nginx/Caddy/Traefik) en 80/443:** corre el
WMS en un puerto interno y enruta tu proxy hacia él. En `.env`:

```
WMS_HTTP_PORT=8080
WMS_HTTPS_PORT=8443
SITE_ADDRESS=:80
```

Luego añade a tu proxy existente una entrada para un (sub)dominio del WMS:

*nginx* (tu proxy termina el TLS, p. ej. con certbot):
```nginx
server {
    server_name wms.midominio.cl;
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

*Caddy* (en tu Caddyfile existente — TLS automático):
```
wms.midominio.cl {
    reverse_proxy 127.0.0.1:8080
}
```

Como el WMS ya enruta `/api` y `/` internamente, tu proxy solo reenvía **todo** a
un puerto. El frontend habla con la API en el mismo origen, así que funciona igual
por IP o por dominio, con o sin TLS de tu proxy.

## 1. Crear el droplet

- **Imagen:** Ubuntu 24.04 LTS (o 22.04 LTS).
- **Tamaño:** mínimo **2 GB RAM / 2 vCPU** (el build del frontend y MongoDB lo
  agradecen; con 1 GB el script crea swap automáticamente, pero 2 GB es lo cómodo).
- **Autenticación:** tu llave SSH.
- **Firewall (DigitalOcean → Networking → Firewalls)** o `ufw`: permite **22, 80,
  443** entrantes.

## 2. Conectarte y obtener el código

```bash
ssh root@TU_IP_DEL_DROPLET
apt-get update -y && apt-get install -y git
```

El repositorio es privado; elige una forma de traerlo:

**a) Token de acceso personal de GitHub (rápido):**
```bash
git clone https://USUARIO:TU_TOKEN@github.com/Jrivasca/wms-insumedent.git
cd wms-insumedent
git checkout claude/crea-development-definitions-8cu566
```

**b) Deploy key (recomendado para permanencia):** crea una llave en el droplet
(`ssh-keygen -t ed25519`), añádela como *Deploy key* de solo lectura en el repo de
GitHub, y clona con la URL `git@github.com:Jrivasca/wms-insumedent.git`.

**c) Sin Git:** copia el proyecto desde tu máquina con
`rsync -av --exclude node_modules --exclude .git ./wms-insumedent root@TU_IP:/opt/`.

## 3. Instalar

Desde la raíz del repo en el droplet:

```bash
sudo ./deploy/deploy.sh
```

El script (idempotente) hace todo:

1. Instala Docker Engine + plugin de Compose si faltan.
2. Crea 2 GB de swap si el droplet tiene poca RAM.
3. Crea `.env` desde `.env.production.example` y **genera secretos fuertes**
   (`JWT_SECRET`, `ENCRYPTION_KEY`, `SEED_TOKEN`).
4. Abre 22/80/443 en `ufw` si está activo.
5. `docker compose -f docker-compose.prod.yml up -d --build`.
6. Espera el `/health` y **carga el seed demo**.
7. Imprime la URL, Swagger y las credenciales demo.

Al terminar tendrás:

| Recurso | URL |
|---------|-----|
| App     | `http://TU_IP/` |
| Swagger | `http://TU_IP/docs` |
| Login   | `admin@demo.cl` / `admin123` |

> ⚠️ Estás en **HTTP**. El token JWT viaja sin cifrar; sirve para una primera
> prueba. Activa HTTPS (paso 5) antes de uso real o con datos sensibles.

## 4. Operación

```bash
cd /ruta/al/repo

# Ver estado y logs
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f backend
docker compose -f docker-compose.prod.yml logs -f worker

# Reiniciar / detener
docker compose -f docker-compose.prod.yml restart
docker compose -f docker-compose.prod.yml down        # conserva los volúmenes/datos

# Actualizar a la última versión
git pull
sudo ./deploy/deploy.sh                                # reconstruye y reinicia
```

**Backup de MongoDB:**
```bash
docker exec wms_mongo mongodump --db wms --archive=/tmp/wms.dump
docker cp wms_mongo:/tmp/wms.dump ./wms-$(date +%F).dump
```
(El volumen `mongo_data` persiste los datos entre reinicios/recreaciones.)

## 5. Activar HTTPS con un dominio (cuando lo tengas)

1. Crea un registro **A** del dominio (p. ej. `wms.midominio.cl`) apuntando a la IP
   del droplet.
2. Edita `.env`:
   ```
   SITE_ADDRESS=wms.midominio.cl
   CORS_ORIGINS=https://wms.midominio.cl
   ```
3. Aplica:
   ```bash
   docker compose -f docker-compose.prod.yml up -d
   ```
   Caddy obtiene y renueva el certificado Let's Encrypt automáticamente (necesita
   80 y 443 abiertos y el DNS ya propagado). **No hace falta reconstruir el
   frontend**: sigue sirviéndose en el mismo origen, ahora bajo HTTPS.

## 6. Deploy automático con GitHub Actions (recomendado)

En vez de entrar tú por SSH, un runner de GitHub puede entrar al droplet y correr
`deploy.sh`. El workflow ya está en `.github/workflows/deploy.yml`.

**Requisitos en el droplet:** que exista, con Ubuntu y los puertos 22/80/443
abiertos (deploy.sh instala Docker la primera vez).

**Configura los secrets** en GitHub → repo → *Settings → Secrets and variables →
Actions → New repository secret*:

| Secret | Valor |
|--------|-------|
| `DROPLET_HOST` | IP pública del droplet (o dominio) |
| `DROPLET_SSH_KEY` | Llave **privada** SSH (contenido completo, formato OpenSSH/PEM) cuya pública está en el droplet (`~/.ssh/authorized_keys`) |
| `DROPLET_USER` | *(opcional)* usuario SSH; por defecto `root` |
| `DROPLET_SSH_PORT` | *(opcional)* puerto SSH; por defecto `22` |

> La llave pública correspondiente debe estar autorizada en el droplet. Si usas el
> usuario `root` (lo habitual en DigitalOcean) no necesitas nada más; si usas otro
> usuario, debe tener `sudo` sin contraseña (NOPASSWD).

**Ejecuta:** pestaña **Actions → "Deploy to droplet" → Run workflow**. El formulario
pide puertos/bind (por defecto pensados para **coexistir con un proxy existente**):

| Input | Por defecto | Para acceso directo por IP |
|-------|-------------|----------------------------|
| `http_port` | `8080` | `80` |
| `https_port` | `8443` | `443` |
| `bind_host` | `127.0.0.1` (solo tu proxy lo alcanza) | `0.0.0.0` |
| `site_address` | `:80` | `:80` o tu dominio |

Tras el deploy, enruta tu reverse proxy hacia `http://127.0.0.1:8080` (snippets de
nginx/Caddy en la sección "Coexistencia con otros proyectos"). El runner:

1. Empaqueta el repo y lo copia al droplet en `/opt/wms-insumedent` (vía SSH+tar;
   no sube `.env`, que lo gestiona el droplet).
2. Corre `sudo ./deploy/deploy.sh` (instala Docker si falta, genera secretos,
   levanta el stack, espera el health y carga el seed).

Es idempotente: vuelve a ejecutarlo para actualizar; conserva el `.env` y los
datos de Mongo del droplet. Para **deploy continuo** en cada push, descomenta el
bloque `push:` del workflow.

## 7. Configurar Defontana real

El sistema arranca con `DEFONTANA_MOCK=true`. Para usar Defontana real:

1. Entra como admin → **Configuración Defontana** y carga las credenciales
   (entorno, cliente/empresa/usuario o email-login). Se guardan **cifradas**.
2. Pulsa **Probar conexión**.
3. Cambia en `.env`: `DEFONTANA_MOCK=false` y reinicia el backend/worker:
   ```bash
   docker compose -f docker-compose.prod.yml up -d backend worker
   ```

## Notas de seguridad

- Cambia/retira el seed demo en producción real (o al menos las credenciales del
  usuario `admin@demo.cl`).
- Los secretos generados quedan en `.env` (no se versiona). Guárdalos a buen recaudo.
- Mantén el firewall restringido a 22/80/443; MongoDB no se expone al exterior.
