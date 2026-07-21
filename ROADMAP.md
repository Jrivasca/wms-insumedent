# Roadmap / Pendientes

Mejoras acordadas para más adelante. No bloquean la demo actual.

---

## Camino a SaaS (producto vendible multi-empresa)

Este WMS pasará a ser un **servicio SaaS** que se venderá a muchas empresas, cada
una con su propio espacio y creciendo en módulos a medida. La base ya ayuda: el
modelo de datos es **multi-tenant** (`tenant_id` en todo, JWT que lo lleva), está
**en contenedores** (portable, sin lock-in) y ya tiene auditoría y secretos cifrados.

**Decisiones tomadas:**
- **Nube:** DigitalOcean (o Hetzner para máximo ahorro) para cómputo.
- **Base de datos:** **MongoDB Atlas** (gestionado, backups, agnóstico de nube).
- **Arquitectura:** mantener el **monolito modular** (FastAPI + worker + React); NO microservicios todavía.
- **Multi-tenancy:** modelo **"pool"** (BD compartida + `tenant_id`); tier de BD dedicada como upsell enterprise más adelante.

### Prioridad 1 — Des-arriesgar datos y base SaaS
1. **Migrar Mongo → MongoDB Atlas** *(pendiente — siguiente paso)*. Crear clúster
   (M0 gratis para dev / M10 para prod), `mongodump` del droplet → `mongorestore`
   al clúster, cambiar `MONGODB_URI` en `.env`, redeploy, y permitir la IP del
   droplet (`137.184.137.130`) en el firewall del clúster. Activar backups automáticos.
2. **Guardia central de aislamiento por tenant**: una capa de acceso a datos que
   SIEMPRE inyecte `tenant_id`, para que ninguna query pueda fugar datos entre empresas.
3. **Backups + restore probado** y export de datos por tenant.

### Prioridad 2 — Empaquetar como producto
4. **Entitlements / planes**: campo `plan` + `features` en el tenant; gating de
   módulos por flag (ya existe el patrón `ERP_CREATE_ENABLED`). Módulos vendibles:
   inventario, picking/packing, despacho, etiquetas, conectores ERP.
5. **Conectores ERP enchufables**: Defontana hoy; arquitectura para sumar otros ERP
   sin tocar el core (ver también pendiente de endpoints reales de Defontana abajo).
6. **Onboarding self-service**: registro → provisión automática del tenant → seed
   base. Separar un **"control plane"** (registro / admin / facturación) del app del tenant.
7. **Facturación: Stripe** (suscripción por empresa o por usuario; planes ↔ entitlements).
8. **Un cliente = un subdominio** (`empresa.tuwms.cl`) o dominio propio (Caddy ya
   soporta TLS automático on-demand).

### Prioridad 3 — Operación y confianza para vender
9. **Observabilidad**: Sentry (errores) + monitoreo de uptime + logs centralizados.
10. **Ambiente de staging** + CI/CD (ya hay GitHub Actions + tests; falta staging y
    deploy continuo).
11. **Seguridad / compliance**: rotación de secretos, política de datos (Ley 19.628
    CL), y SOC2 cuando se venda a enterprise.

### Cómo funcionará en la práctica (tenants, usuarios, admin, dominios)

**Creación de tenant + usuarios** (la base ya existe: `users` tienen `tenant_id` +
`role`, el JWT lleva el `tenant_id`, y el `seed` ya crea tenant + admin + datos base):
1. **Provisionar el tenant**: crear el registro (nombre, plan, estado) + su primer
   **usuario admin** + seed base (bodega, ubicaciones). Generalizar el `seed` en una
   función `create_tenant`.
2. El **admin del cliente** entra y crea/invita a su equipo (operarios, supervisores),
   cada uno con su rol; solo ven los datos de SU empresa.

**Dos niveles de admin (no confundir):**
- **Admin del cliente** (gestiona SUS usuarios/bodegas/config) → es **producto**;
  construir la UI "Equipo" cuando un cliente la necesite.
- **Admin de la plataforma** (crear/suspender empresas, plan/módulos, uso, cobro) →
  es el **control plane**, separado del app del tenant.

**Estrategia: a medida, no un módulo grande de entrada.**
- Primeros clientes (1–10): provisionar con **script/endpoint protegido** (el `seed`
  ya es casi eso); crear usuarios por script si hace falta.
- Después: UI de gestión de usuarios del cliente (producto).
- Cuando el volumen lo justifique: **control plane** real + onboarding self-service + Stripe.

**Dominios / subdominios:**
- **DNS comodín**: `*.midominio.app` → IP del servidor, configurado UNA vez; cubre
  todos los tenants (`acme.midominio.app`, etc.) sin crear un DNS por cliente.
- El subdominio **identifica** al tenant (el backend lee el `Host`), pero la
  **seguridad real** es el login + `tenant_id` en la base. Los usuarios se autentican
  normal; el subdominio solo da contexto/branding. TLS automático con Caddy.
- **Se puede partir SIN subdominios** (un solo `app.midominio.app`; el tenant sale del
  JWT). Agregar subdominios (branding) y **dominios propios del cliente** (CNAME →
  upsell) más adelante.

### Escalamiento (cuando toque)
- **Etapa 1 (1–20 clientes):** 1 droplet + Atlas + BD compartida. ~US$30–60/mes.
- **Etapa 2 (20–200):** backend con réplicas, Atlas con backups/réplica, Spaces/S3,
  Sentry, staging, Stripe + entitlements.
- **Etapa 3 (200+):** Kubernetes (DOKS/EKS), tier de BD dedicada para enterprise,
  multi-región, SSO, SOC2.

---

## Pendiente (funcional)

- **Endpoints reales de Defontana para crear producto / crear pedido.** La
  integración hoy sólo **lee** productos y pedidos desde Defontana; su API no
  expone (o no se ha confirmado) endpoints para **crear** un producto o un pedido.
  Por eso los jobs `create_product` y `create_order` responden OK en mock y lanzan
  `NotImplementedError` en modo real, y las acciones "Nuevo producto / pedido" están
  ocultas en la UI (flag `ERP_CREATE_ENABLED` en `frontend/src/config.ts`). Cuando
  se confirmen los endpoints reales, conectarlos en `DefontanaConnector.create_product`
  / `create_order` (`backend/app/integrations/defontana/client.py`) y poner el flag en true.
  *(La recepción → `Inventory/Insert` sí sincroniza de verdad.)*

- **Nombre y logo del producto.** Pendiente de definir (lo verá el dueño). Cuando esté,
  aplicar en: ícono/logo, nombre en el menú (`Layout.tsx`) y favicon.

---

## Hecho (referencia rápida)

- Catálogo dental real de INSUMEDENT en la demo (1251 productos con stock real, 17 categorías).
- Flujo completo **picking → packing → despacho** clickeable, operable sin pistola lectora.
- Escáner con **soporte móvil**: cámara para escanear + teclado en pantalla al tocar.
- **"Volver a escanear"** para corregir líneas en picking y packing.
- **Retomar** tareas en curso: filas clickeables en Picking/Packing y "Continuar picking" en Pedidos.
- **Impresión de etiquetas** de productos con código de barras EAN-13 (A4 o impresora térmica).
- **Etiqueta por bulto (1/N)** en packing: cliente, productos y cantidad por bulto.
- **Recepción de mercadería** (con ubicación → etiqueta → sync ERP real vía `Inventory/Insert`).
- **Alta de producto / pedido** (backend listo, con job de sync; UI oculta hasta endpoints reales).
- **Paginación** de listados (productos, saldos, movimientos).
- **Submenú Inventario** (Saldos / Recepción / Transferencia / Ajuste) con selector de producto.
- **Transportista** como lista desplegable (Bluexpress / NewTrans / Otro).
