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


async def crear_referencias(
    tenant_id: str,
    *,
    sku: str = "SKU1",
    warehouse_code: str = "BOD1",
    locations: tuple = ("A-01",),
) -> dict:
    """Crear producto, bodega y ubicaciones REALES y devolver sus ids.

    Los movimientos de inventario validan que las tres referencias existan y calcen
    (``inventory_service.assert_references_exist``), así que un test no puede seguir
    inventando ids sueltos como ``"wh1"``: probaría un camino que la API ya no permite.
    Devuelve ``{"product_id", "warehouse_id", "<código de ubicación>": id, ...}``.
    """
    from app.core.database import get_database
    from app.models import Collections

    db = get_database()
    producto = await db[Collections.PRODUCTS].insert_one(
        {"tenant_id": tenant_id, "sku": sku, "name": "Prod", "is_active": True}
    )
    bodega = await db[Collections.WAREHOUSES].insert_one(
        {"tenant_id": tenant_id, "code": warehouse_code, "name": warehouse_code,
         "is_active": True}
    )
    refs = {
        "product_id": str(producto.inserted_id),
        "warehouse_id": str(bodega.inserted_id),
    }
    for code in locations:
        loc = await db[Collections.LOCATIONS].insert_one(
            {"tenant_id": tenant_id, "warehouse_id": refs["warehouse_id"], "code": code,
             "type": "storage", "is_active": True}
        )
        refs[code] = str(loc.inserted_id)
    return refs
