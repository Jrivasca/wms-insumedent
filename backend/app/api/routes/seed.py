from fastapi import APIRouter, Header, HTTPException

from app.core.config import settings
from app.seed import run_seed

router = APIRouter(prefix="/seed", tags=["seed"])


@router.post("")
async def seed(x_seed_token: str = Header(default="")):
    """Protected demo seed endpoint.

    Requires header ``X-Seed-Token`` matching the ``SEED_TOKEN`` env var.
    """
    if x_seed_token != settings.seed_token:
        raise HTTPException(status_code=403, detail="Invalid seed token")
    return await run_seed()
