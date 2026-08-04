from functools import lru_cache
from typing import Annotated, List

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables / .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Application
    app_name: str = "WMS Defontana"
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


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
