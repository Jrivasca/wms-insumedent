"""Configuración del conector Defontana: entorno de pruebas, verbo de Inventory/Insert y
un OK simulado que no se confunde con uno real."""
import pytest
from bson import ObjectId

from app.core.config import settings
from app.core.database import get_database
from app.integrations.defontana.client import DefontanaConnector
from app.models import Collections
from app.schemas.integration import DefontanaConfigRequest
from app.services import integration_service

pytestmark = pytest.mark.asyncio


async def _tenant() -> str:
    r = await get_database()[Collections.TENANTS].insert_one({"name": "T", "is_active": True})
    return str(r.inserted_id)


async def test_configure_test_environment_points_to_replapi_and_encrypts_password():
    tenant_id = await _tenant()
    status = await integration_service.configure(
        tenant_id,
        DefontanaConfigRequest(
            environment="test", auth_mode="client_company_user",
            client="C1", company="E1", user="U1", password="secreto",
        ),
        actor="admin",
    )
    assert status["environment"] == "test"
    assert status["auth_mode"] == "client_company_user"
    assert status["base_url"] == settings.defontana_test_base_url
    assert "replapi.defontana.com" in status["base_url"]

    conn = await get_database()[Collections.ERP_CONNECTIONS].find_one({"tenant_id": tenant_id})
    assert "password" not in conn
    assert conn["password_encrypted"] and conn["password_encrypted"] != "secreto"


async def test_inventory_insert_uses_post(monkeypatch):
    monkeypatch.setattr(settings, "defontana_mock", False)
    connector = DefontanaConnector(str(ObjectId()))
    calls = []

    async def fake_request(method, path, **kwargs):
        calls.append((method, path))
        return {"ok": True}

    monkeypatch.setattr(connector, "_request", fake_request)
    await connector.create_inventory_document({"externalDocumentID": "WMS-REC-1"})
    assert calls == [("POST", "/Inventory/Insert")]


async def test_stored_token_with_naive_expiry_is_reused_not_crashing(monkeypatch):
    """Motor devuelve datetimes naive: comparar con now_utc() (aware) reventaba en la
    segunda llamada real a Defontana ('can't compare offset-naive and offset-aware')."""
    from datetime import datetime, timedelta

    from app.core.security import encrypt_secret
    from app.integrations.defontana.token_manager import DefontanaTokenManager

    monkeypatch.setattr(settings, "defontana_mock", False)
    tenant_id = await _tenant()
    await get_database()[Collections.ERP_TOKENS].insert_one({
        "tenant_id": tenant_id, "erp": "defontana", "status": "active",
        "access_token_encrypted": encrypt_secret("TOKEN-GUARDADO"),
        "expires_at": datetime.utcnow() + timedelta(minutes=30),  # naive, como Motor
    })
    assert await DefontanaTokenManager().get_valid_token(tenant_id) == "TOKEN-GUARDADO"


async def test_token_ttl_uses_expires_in_from_auth_response():
    from datetime import timedelta

    from app.core.utils import now_utc
    from app.integrations.defontana.token_manager import DefontanaTokenManager, _aware

    tenant_id = await _tenant()
    await DefontanaTokenManager()._persist_token(tenant_id, "T", expires_in=3600)
    doc = await get_database()[Collections.ERP_TOKENS].find_one({"tenant_id": tenant_id})
    remaining = _aware(doc["expires_at"]) - now_utc()
    assert timedelta(minutes=54) < remaining <= timedelta(minutes=55)


async def test_check_in_mock_mode_says_it_did_not_contact_defontana(monkeypatch):
    monkeypatch.setattr(settings, "defontana_mock", True)
    tenant_id = await _tenant()
    result = await integration_service.check(tenant_id)
    assert result["mock"] is True
    assert "simulado" in result["message"]
