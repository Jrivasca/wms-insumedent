from typing import Any, Dict

from app.integrations.defontana.client import DefontanaConnector


async def create_inventory_document(tenant_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Create an inventory document in Defontana (section 8.4).

    Every inventory document carries an ``externalDocumentID``. Before inserting,
    we check whether Defontana already has it to guarantee idempotency on retries.
    """
    connector = DefontanaConnector(tenant_id)

    external_id = payload.get("externalDocumentID")
    if external_id:
        existing = await connector.get_inventory_document_by_external_id(external_id)
        if existing:
            return {
                "already_exists": True,
                "external_document_id": external_id,
                "response": existing,
            }

    response = await connector.create_inventory_document(payload)
    return {"already_exists": False, "response": response}
