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
