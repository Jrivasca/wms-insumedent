from typing import Any, Dict, Optional

from fastapi import HTTPException, status

from app.core.config import settings
from app.core.tenant_db import tenant_db
from app.core.security import encrypt_secret
from app.core.utils import now_utc, serialize
from app.models import Collections
from app.models.integration import ErpConnectionStatus, ErpProvider
from app.schemas.integration import DefontanaConfigRequest
from app.integrations.defontana.client import DefontanaConnector
from app.integrations.defontana import order_sync, product_sync, warehouse_sync

ERP = ErpProvider.DEFONTANA.value


def sale_api_available(connection: Optional[Dict[str, Any]]) -> bool:
    """``Sale/*`` (productos, bodegas) es del módulo Ventas, que Insumedent no contrató: solo
    se permite en el ambiente de pruebas, en modo simulado o con
    ``DEFONTANA_SALE_API_ENABLED``."""
    if settings.defontana_sale_api_enabled or settings.defontana_mock:
        return True
    environment = (connection or {}).get("environment") or settings.defontana_env
    return str(environment).lower() not in ("production", "prod")


def _orders_auto_sync(connection: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    conn = connection or {}
    return {
        "enabled": settings.defontana_orders_sync_enabled and not settings.defontana_mock,
        "interval_minutes": settings.defontana_orders_sync_interval_minutes,
        "hours": settings.defontana_orders_sync_hours,
        "weekdays_only": settings.defontana_orders_sync_weekdays_only,
        "last_run_at": conn.get("last_orders_sync_at"),
        "last_summary": conn.get("last_orders_sync_summary"),
        "last_error": conn.get("last_orders_sync_error"),
    }


async def _require_sale_api(tenant_id: str) -> None:
    if not sale_api_available(await _connection(tenant_id)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "La API de Ventas de Defontana (Sale/*) no está contratada: los productos se "
                "cargan con el importador de Excel y las bodegas en el mantenedor."
            ),
        )


async def _connection(tenant_id: str) -> Dict[str, Any]:
    db = tenant_db(tenant_id)
    return await db[Collections.ERP_CONNECTIONS].find_one({"tenant_id": tenant_id, "erp": ERP})


async def get_status(tenant_id: str) -> Dict[str, Any]:
    conn = await _connection(tenant_id)
    if not conn:
        return {
            "configured": False,
            "status": "not_configured",
            "environment": settings.defontana_env,
            "mock": settings.defontana_mock,
            "last_check_at": None,
            "last_error": None,
            "sale_api_available": sale_api_available(None),
            "orders_auto_sync": _orders_auto_sync(None),
        }
    data = serialize(conn)
    return {
        "configured": True,
        "status": data.get("status"),
        "environment": data.get("environment"),
        "auth_mode": data.get("auth_mode"),
        "base_url": data.get("base_url"),
        "mock": settings.defontana_mock,
        "last_check_at": data.get("last_check_at"),
        "last_error": data.get("last_error"),
        "sale_api_available": sale_api_available(data),
        "orders_auto_sync": _orders_auto_sync(data),
    }


async def configure(tenant_id: str, config: DefontanaConfigRequest, actor: str) -> Dict[str, Any]:
    db = tenant_db(tenant_id)
    now = now_utc()

    base_url = config.base_url or (
        settings.defontana_prod_base_url
        if config.environment.value in ("production", "prod")
        else settings.defontana_test_base_url
    )

    update: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "erp": ERP,
        "environment": config.environment.value,
        "auth_mode": config.auth_mode.value,
        "client": config.client,
        "company": config.company,
        "user": config.user,
        "email": config.email,
        "base_url": base_url,
        "status": ErpConnectionStatus.CONFIGURED.value,
        "updated_at": now,
        "updated_by": actor,
    }
    # Never store credentials in plain text (section 6.3 / 12).
    if config.password:
        update["password_encrypted"] = encrypt_secret(config.password)
    if config.email_password:
        update["email_password_encrypted"] = encrypt_secret(config.email_password)

    await db[Collections.ERP_CONNECTIONS].update_one(
        {"tenant_id": tenant_id, "erp": ERP},
        {"$set": update, "$setOnInsert": {"created_at": now, "created_by": actor}},
        upsert=True,
    )
    return await get_status(tenant_id)


async def check(tenant_id: str) -> Dict[str, Any]:
    db = tenant_db(tenant_id)
    connector = DefontanaConnector(tenant_id)
    now = now_utc()
    try:
        ok = await connector.health_check()
        status_value = (
            ErpConnectionStatus.CONNECTED.value if ok else ErpConnectionStatus.ERROR.value
        )
        error = None if ok else "Health check returned a non-OK response"
    except Exception as exc:  # noqa: BLE001 - surface any connector failure to the UI
        ok = False
        status_value = ErpConnectionStatus.ERROR.value
        error = str(exc)

    await db[Collections.ERP_CONNECTIONS].update_one(
        {"tenant_id": tenant_id, "erp": ERP},
        {
            "$set": {
                "status": status_value,
                "last_check_at": now,
                "last_error": error,
                "updated_at": now,
            },
            "$setOnInsert": {
                "tenant_id": tenant_id,
                "erp": ERP,
                "created_at": now,
            },
        },
        upsert=True,
    )
    if settings.defontana_mock:
        # En modo simulado el OK no significa nada: que la UI no lo confunda con uno real.
        message = "Modo simulado (DEFONTANA_MOCK=true): no se contactó a Defontana"
    else:
        message = "Conexión Defontana OK" if ok else (error or "Error de conexión")
    return {
        "status": status_value,
        "ok": ok,
        "mock": settings.defontana_mock,
        "message": message,
    }


async def run_sync_products(tenant_id: str, actor: str) -> Dict[str, Any]:
    await _require_sale_api(tenant_id)
    summary = await product_sync.sync_products(tenant_id, actor)
    return {"status": "ok", "type": "sync_products", "summary": summary}


async def run_sync_warehouses(tenant_id: str, actor: str) -> Dict[str, Any]:
    await _require_sale_api(tenant_id)
    summary = await warehouse_sync.sync_warehouses(tenant_id, actor)
    return {"status": "ok", "type": "sync_warehouses", "summary": summary}


async def run_sync_orders(tenant_id: str, actor: str) -> Dict[str, Any]:
    summary = await order_sync.sync_orders(tenant_id, actor=actor)
    return {"status": "ok", "type": "sync_orders", "summary": summary}
