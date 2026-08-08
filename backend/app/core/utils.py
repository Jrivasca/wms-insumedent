from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def page(items: List[Any], total: int, limit: int, offset: int) -> Dict[str, Any]:
    """Standard paginated-list envelope returned by the ``list_*`` services.

    The frontend consumes ``{items, total, limit, offset}`` (see ``Page<T>`` in the
    web app) so a table can show "X–Y de N" and disable the next-page control.
    """
    return {"items": items, "total": total, "limit": limit, "offset": offset}


def to_object_id(value: Any) -> Optional[ObjectId]:
    if value is None:
        return None
    if isinstance(value, ObjectId):
        return value
    try:
        return ObjectId(str(value))
    except Exception:
        return None


def serialize(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Convert a Mongo document into a JSON-friendly dict.

    - ``_id`` becomes a string ``id``
    - ObjectId values become strings
    - datetimes become ISO-8601 strings
    """
    if doc is None:
        return None

    result: Dict[str, Any] = {}
    for key, value in doc.items():
        if key == "_id":
            result["id"] = str(value)
        else:
            result[key] = _serialize_value(value)
    return result


def _serialize_value(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _serialize_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_serialize_value(v) for v in value]
    return value
