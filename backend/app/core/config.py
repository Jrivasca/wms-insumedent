import base64
from functools import lru_cache
from typing import Annotated, List

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables / .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Application
    app_name: str = "Selarix WMS"
    environment: str = "development"
    api_port: int = 8000

    # MongoDB
    mongodb_uri: str = "mongodb://mongo:27017"
    mongodb_db: str = "wms"

    # Auth / Security
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 720
    encryption_key: str = ""
    seed_token: str = "seed-me"

    # Defontana
    defontana_mock: bool = True
    defontana_env: str = "test"
    defontana_test_base_url: str = "https://replapi.defontana.com/api"
    defontana_prod_base_url: str = "https://api.defontana.com/api"
    # Días hacia atrás para traer pedidos EN DESPACHO desde Defontana (Order/List).
    defontana_orders_window_days: int = 90
    # Sincronización automática de pedidos (worker). Apagada por defecto. Corre cada
    # N minutos dentro del horario "HH:MM-HH:MM" (hora de ``defontana_timezone``).
    defontana_orders_sync_enabled: bool = False
    defontana_orders_sync_interval_minutes: int = 15
    defontana_orders_sync_hours: str = "08:00-19:00"
    defontana_orders_sync_weekdays_only: bool = True
    # Sincronización diaria de lotes + foto de stock del ERP (de madrugada: son ~70 llamadas).
    defontana_stock_sync_enabled: bool = False
    defontana_stock_sync_at: str = "03:30"
    defontana_timezone: str = "America/Santiago"
    # Movimientos del WMS que cambian la cantidad total (recepción y ajuste/merma) →
    # Inventory/Insert. Tipos de documento y motivos definidos (decisión A.1) y PROBADOS contra
    # la API de pruebas el 2026-09-19: cada combinación se creó y se borró. El envío sigue con su
    # propio flag, apagado, porque el centro de negocio va dentro de cada documento y todavía
    # está pendiente de confirmar por Insumedent (A.2).
    defontana_inventory_sync_enabled: bool = False
    # Parte de Entrada: la sugerencia de Defontana para ingresar stock.
    defontana_reception_document_type: str = "PE"
    defontana_adjustment_in_document_type: str = "XAJ_ENT_UN"
    defontana_adjustment_out_document_type: str = "XAJ_SAL_UNID"
    defontana_reception_reason_id: str = "COMPRA"
    # Motivo de los ajustes, separado por sentido: un ajuste negativo o una merma no puede
    # viajar con el motivo de una entrada (antes había uno solo que, vacío, caía en COMPRA).
    defontana_adjustment_in_reason_id: str = "ENTRADA"
    defontana_adjustment_out_reason_id: str = "SALIDA"
    defontana_business_center: str = "EMPNEGVTAVTA000"
    defontana_reception_centralizable: bool = False
    # Conciliación WMS ← Defontana: código de la ubicación donde queda lo que aparece de más en
    # el ERP hasta que bodega lo ubique (decisión A.3). SIN-UBICAR es de tipo recepción, no
    # pickeable, y se crea por defecto en toda bodega nueva.
    defontana_reconcile_location_code: str = "SIN-UBICAR"
    # Corrida diaria de madrugada, después de la foto de stock (decisión A.4). Aplica sola las
    # diferencias chicas; las que superan DEFONTANA_RECONCILE_REVIEW_UNITS quedan para revisión
    # humana (A.5) y un supervisor las aprueba una por una en Stock ERP vs WMS. Apagada por
    # defecto: la primera corrida conviene hacerla a mano, porque el WMS arranca muy distinto
    # del ERP.
    defontana_reconcile_enabled: bool = False
    defontana_reconcile_at: str = "04:30"
    defontana_reconcile_review_units: float = 20

    # Push de altas hacia el ERP (crear producto / pedido / documento de entrada).
    # En operación stand-alone (sin Defontana) va en false: el WMS opera solo y no
    # encola trabajos de sincronización que no tienen a dónde ir.
    erp_sync_enabled: bool = False

    # Guía de despacho → Order/DispatchOrder (B.1). El envío va detrás de ``erp_sync_enabled``
    # (apagado): confirmar un despacho con el flag apagado deja la guía SOLO en el WMS, no la
    # emite en el ERP. Valores del ``dispatchInfo`` confirmados leyendo guías GDVELECT reales
    # (``dispatchTypeData``) el 2026-09-22: tipo de bien 1 = "Constituye una venta", tipo de
    # despacho 1 = "Por cuenta del cliente".
    defontana_dispatch_assets_type: str = "1"
    defontana_dispatch_type: str = "1"
    # Confirmado por la spec de Dispatch/Save (Luis, 2026-09-23): 1 = "Venta del Giro".
    defontana_dispatch_transaction_type: str = "1"
    # ``motive`` de la bodega: ``VENTA`` (confirmado en el ejemplo que devolvió Luis, 2026-09-25).
    defontana_dispatch_motive: str = "VENTA"

    # Guía de despacho → Dispatch/Save (B.1, método recomendado por Defontana: soporta lote/serie
    # por línea). Reemplaza a Order/DispatchOrder. Sigue detrás de ``erp_sync_enabled`` (apagado).
    # ``IsTransferDocument=true`` registra y contabiliza la guía pero NO la envía al SII (útil para
    # probar sin emitir un DTE real; igual consume folio y no se puede borrar) — por eso el default.
    defontana_dispatch_is_transfer_document: bool = True
    # Código del tipo de documento de la guía (GetDocumentInfo). Pendiente: lo define Insumedent.
    defontana_dispatch_document_type: str = ""
    # Cuentas contables de los asientos (accountNumber, sin puntos). Valores del ejemplo de Luis
    # (2026-09-25), a confirmar por la contabilidad de Insumedent antes de encender la guía:
    # cliente 1110401001, venta e inventario de línea 1110801001, inventario de bodega 4110101001.
    # Vacío = el payload los deja en blanco para completar.
    defontana_dispatch_client_account: str = ""
    defontana_dispatch_sale_account: str = ""
    defontana_dispatch_inventory_account: str = ""
    defontana_dispatch_storage_account: str = ""

    # Inventory
    allow_negative_stock: bool = False

    # Consulta pública de bultos por QR: días de validez del enlace (token) del bulto.
    public_bulto_ttl_days: int = 90

    # Web Push (VAPID) — notificaciones push Fase 2. Vacío = push deshabilitado (la
    # Fase 1 in-app sigue funcionando igual). `vapid_public_key` es la application
    # server key (base64url) que consume el navegador; `vapid_private_key` es el PEM
    # de la clave EC P-256, codificado en base64 para viajar en una sola línea del .env.
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = "mailto:notificaciones@selarix.cl"

    # Ingesta por carpeta (folder-watch) — Plan 1 Fase 1/2. Lee PDFs de pedidos y
    # Excel de productos desde un directorio local (una carpeta de nube sincronizada
    # por rclone) cada N segundos. Vacío/false = deshabilitado (el import manual por
    # la UI sigue igual). ``intake_inbound_dir`` es la base y contiene las subcarpetas
    # ``pedidos/ productos/ procesados/ revisar/``. ``intake_tenant_id`` es el tenant
    # dueño; si queda vacío y existe un único tenant, se usa ese.
    intake_enabled: bool = False
    intake_inbound_dir: str = ""
    intake_tenant_id: str = ""
    intake_interval_seconds: int = 120
    # Folder-watch de productos (Excel). Por defecto OFF: el catálogo se importa solo
    # de forma MANUAL (botón "Importar Excel"). El folder-watch de pedidos es aparte.
    intake_products_enabled: bool = False

    # Lotes y vencimiento (Plan 1 Fase 5). ``expiry_alert_days`` = ventana para avisar
    # "por vencer"; el worker revisa cada ``expiry_check_interval_seconds``.
    expiry_alert_days: int = 30
    expiry_check_interval_seconds: int = 21600  # 6 h

    # CORS — orígenes separados por coma (p. ej. "https://a.cl,https://b.cl").
    # NoDecode evita que pydantic-settings intente JSON-decodificar el valor del
    # env antes de correr el validador de abajo; sin esto, un valor como "*" o un
    # dominio suelto crashea el arranque con SettingsError.
    cors_origins: Annotated[List[str], NoDecode] = ["http://localhost:5173", "http://localhost:3000"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_cors(cls, value):
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def defontana_base_url(self) -> str:
        if self.defontana_env.lower() in ("production", "prod"):
            return self.defontana_prod_base_url
        return self.defontana_test_base_url

    @property
    def push_enabled(self) -> bool:
        return bool(self.vapid_public_key and self.vapid_private_key)

    @property
    def vapid_private_pem(self) -> str:
        """The EC private key as PEM text. Stored base64-encoded in the env to keep
        the multi-line PEM on a single line; a raw PEM is also accepted."""
        if not self.vapid_private_key:
            return ""
        value = self.vapid_private_key.strip()
        if "BEGIN" in value:
            return value
        try:
            return base64.b64decode(value).decode("utf-8")
        except Exception:
            return value


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
