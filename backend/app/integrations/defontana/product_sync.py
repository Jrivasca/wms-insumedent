from typing import Any, Dict

from app.core.tenant_db import tenant_db
from app.core.utils import now_utc
from app.models import Collections
from app.models.product import BarcodeSource, BarcodeType
from app.integrations.defontana.client import DefontanaConnector
from app.integrations.defontana.mapper import DefontanaMapper


def _guess_barcode_type(barcode: str) -> str:
    if barcode and barcode.isdigit() and len(barcode) == 13:
        return BarcodeType.EAN13.value
    return BarcodeType.SUPPLIER.value


async def sync_products(tenant_id: str, actor: str = "system") -> Dict[str, Any]:
    db = tenant_db(tenant_id)
    connector = DefontanaConnector(tenant_id)
    raw_products = await connector.get_products()

    created = updated = barcodes_added = 0
    now = now_utc()

    for raw in raw_products:
        mapped = DefontanaMapper.map_product(raw)
        barcode = mapped.pop("barcode", None)

        existing = await db[Collections.PRODUCTS].find_one(
            {"tenant_id": tenant_id, "sku": mapped["sku"]}
        )
        doc = {
            **mapped,
            "tenant_id": tenant_id,
            "is_active": True,
            "updated_at": now,
            "updated_by": actor,
        }
        if existing:
            await db[Collections.PRODUCTS].update_one(
                {"_id": existing["_id"]}, {"$set": doc}
            )
            product_id = str(existing["_id"])
            updated += 1
        else:
            doc["created_at"] = now
            doc["created_by"] = actor
            result = await db[Collections.PRODUCTS].insert_one(doc)
            product_id = str(result.inserted_id)
            created += 1

        if barcode:
            existing_bc = await db[Collections.BARCODES].find_one(
                {"tenant_id": tenant_id, "barcode": str(barcode)}
            )
            if not existing_bc:
                await db[Collections.BARCODES].insert_one(
                    {
                        "tenant_id": tenant_id,
                        "product_id": product_id,
                        "barcode": str(barcode),
                        "type": _guess_barcode_type(str(barcode)),
                        "source": BarcodeSource.DEFONTANA.value,
                        "is_active": True,
                        "created_at": now,
                        "updated_at": now,
                    }
                )
                barcodes_added += 1

    return {
        "synced": len(raw_products),
        "created": created,
        "updated": updated,
        "barcodes_added": barcodes_added,
    }
