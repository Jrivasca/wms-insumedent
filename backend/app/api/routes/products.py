from typing import Optional

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, get_current_user
from app.schemas.product import BarcodeCreate
from app.services import product_service

router = APIRouter(prefix="/products", tags=["products"])


@router.get("")
async def list_products(
    search: Optional[str] = None, user: CurrentUser = Depends(get_current_user)
):
    return await product_service.list_products(user.tenant_id, search)


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
