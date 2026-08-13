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

    # Push de altas hacia el ERP (crear producto / pedido / documento de entrada).
    # En operación stand-alone (sin Defontana) va en false: el WMS opera solo y no
    # encola trabajos de sincronización que no tienen a dónde ir.
    erp_sync_enabled: bool = False

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
