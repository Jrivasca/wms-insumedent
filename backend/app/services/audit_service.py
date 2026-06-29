from typing import Any, Optional

from app.core.database import get_database
from app.core.logging import sanitize_payload
from app.core.utils import now_utc
from app.models import Collections


async def log_action(
    *,
    tenant_id: str,
    user_id: Optional[str],
    action: str,
    entity_type: str,
    entity_id: Optional[str] = None,
    before: Any = None,
    after: Any = None,
    metadata: Optional[dict] = None,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> None:
    """Write an audit log entry for a critical action.

    Payloads are sanitized to avoid persisting secrets.
    """
    db = get_database()
    await db[Collections.AUDIT_LOGS].insert_one(
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "before": sanitize_payload(before),
            "after": sanitize_payload(after),
            "metadata": sanitize_payload(metadata or {}),
            "ip": ip,
            "user_agent": user_agent,
            "created_at": now_utc(),
        }
    )
