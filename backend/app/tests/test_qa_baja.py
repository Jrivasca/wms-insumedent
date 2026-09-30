"""Hallazgos de prioridad BAJA de la QA funcional del 2026-09-29 que tocan el backend."""
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.core.database import get_database
from app.models import Collections
from app.schemas.product import ProductCreate
from app.services import product_service


def test_el_precio_del_producto_no_puede_ser_negativo():
    base = {"sku": "S1", "name": "Producto"}
    for campo in ("cost", "sale_price"):
        with pytest.raises(ValidationError) as exc:
            ProductCreate(**base, **{campo: -100})
        assert campo in {e["loc"][0] for e in exc.value.errors()}
    # 0 sí: hay artículos sin costo cargado.
    assert ProductCreate(**base, cost=0, sale_price=0).cost == 0


@pytest.mark.asyncio
async def test_un_sku_duplicado_responde_409_en_espanol():
    """La QA lo dejó sin probar. Ya estaba cubierto; queda el test para que no se pierda."""
    tid = "tA"
    await product_service.create_product(tid, {"sku": "ANES014", "name": "Anestesia"}, "u1",
                                         sync_erp=False)
    with pytest.raises(HTTPException) as exc:
        await product_service.create_product(tid, {"sku": "ANES014", "name": "Otra"}, "u1",
                                             sync_erp=False)
    assert exc.value.status_code == 409
    assert "SKU" in exc.value.detail
    assert await get_database()[Collections.PRODUCTS].count_documents({"tenant_id": tid}) == 1
