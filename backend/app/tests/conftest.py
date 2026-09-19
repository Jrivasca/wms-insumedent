import pytest
from mongomock_motor import AsyncMongoMockClient

from app.api.deps import CurrentUser
from app.core import database


@pytest.fixture(autouse=True)
def mock_database():
    """Replace the global database with an in-memory mongomock instance per test."""
    client = AsyncMongoMockClient()
    database.set_database(client["wms_test"])
    yield database.get_database()
    database.set_database(None)


def make_user(user_doc: dict, role: str = "admin") -> CurrentUser:
    return CurrentUser(
        id=str(user_doc["_id"]),
        tenant_id=user_doc["tenant_id"],
        name=user_doc.get("name", ""),
        email=user_doc.get("email", ""),
        role=user_doc.get("role", role),
        allowed_warehouse_ids=user_doc.get("allowed_warehouse_ids", []),
    )


@pytest.fixture(autouse=True)
def default_settings(monkeypatch):
    """Cada test corre con la configuración por defecto de ``config.py``, no con el ``.env``
    de quien lo ejecuta. Dentro del contenedor, el ``.env`` real apaga el modo simulado de
    Defontana y enciende sincronizaciones: cuatro tests escritos para el modo simulado
    fallaban intentando autenticarse contra el ERP de verdad. El test que necesite otro valor
    lo fija él mismo con ``monkeypatch``, que corre después de este fixture."""
    from app.core.config import settings

    for name, field in type(settings).model_fields.items():
        if field.is_required():
            continue
        monkeypatch.setattr(settings, name, field.get_default(call_default_factory=True))
