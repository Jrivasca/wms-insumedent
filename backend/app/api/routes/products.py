from typing import Optional

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, get_current_user, require_supervisor
from app.schemas.product import BarcodeCreate, ProductCreate
from app.services import product_service
from app.services.audit_service import log_action

router = APIRouter(prefix="/products", tags=["products"])


@router.get("")
async def list_products(
    search: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    user: CurrentUser = Depends(get_current_user),
):
    return await product_service.list_products(user.tenant_id, search, limit, offset)


@router.post("", status_code=201)
async def create_product(
    payload: ProductCreate, user: CurrentUser = Depends(require_supervisor)
):
    product = await product_service.create_product(
        user.tenant_id, payload.model_dump(), user.id
    )
    await log_action(
        tenant_id=user.tenant_id,
        user_id=user.id,
        action="product_create",
        entity_type="product",
        entity_id=product["id"],
        metadata={"sku": product["sku"]},
        ip=user.ip,
        user_agent=user.user_agent,
    )
    return product


@router.get("/barcode/{barcode}")
async def get_by_barcode(barcode: str, user: CurrentUser = Depends(get_current_user)):
    return await product_service.get_by_barcode(user.tenant_id, barcode)


@router.get("/{product_id}")
async def get_product(product_id: str, user: CurrentUser = Depends(get_current_user)):
    return await product_service.get_product(user.tenant_id, product_id)


@router.post("/{product_id}/barcodes", status_code=201)
async def add_barcode(
    product_id: str, payload: BarcodeCreate, user: CurrentUser = Depends(get_current_user)
):
    return await product_service.add_barcode(
        user.tenant_id, product_id, payload.barcode, payload.type.value, user.id
    )
