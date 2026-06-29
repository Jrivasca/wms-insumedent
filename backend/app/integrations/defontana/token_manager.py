"""Centralized Defontana token management (section 7.1).

Rules enforced here:
- One token per tenant+ERP, stored encrypted in ``erp_tokens``.
- Never request a new token on every call; reuse the stored one until it expires.
- Refresh only when missing/expired (or once on a 401 from a caller).
"""
from datetime import timedelta
from typing import Optional

import httpx

from app.core.config import settings
from app.core.database import get_database
from app.core.logging import get_logger
from app.core.security import decrypt_secret, encrypt_secret
from app.core.utils import now_utc
from app.models import Collections
from app.models.integration import ErpAuthMode, ErpTokenStatus

logger = get_logger(__name__)

# Refresh a little before the nominal expiry to avoid edge-of-expiry failures.
TOKEN_TTL_MINUTES = 50


class DefontanaAuthError(Exception):
    pass


class DefontanaTokenManager:
    erp = "defontana"

    async def _get_connection(self, tenant_id: str) -> Optional[dict]:
        db = get_database()
        return await db[Collections.ERP_CONNECTIONS].find_one(
            {"tenant_id": tenant_id, "erp": self.erp}
        )

    async def _stored_token(self, tenant_id: str) -> Optional[dict]:
        db = get_database()
        return await db[Collections.ERP_TOKENS].find_one(
            {"tenant_id": tenant_id, "erp": self.erp}
        )

    async def get_valid_token(self, tenant_id: str) -> str:
        token_doc = await self._stored_token(tenant_id)
        if token_doc and token_doc.get("expires_at"):
            expires_at = token_doc["expires_at"]
            if expires_at > now_utc() and token_doc.get("status") == ErpTokenStatus.ACTIVE.value:
                decrypted = decrypt_secret(token_doc.get("access_token_encrypted", ""))
                if decrypted:
                    return decrypted
        return await self.refresh_token(tenant_id)

    async def refresh_token(self, tenant_id: str) -> str:
        token = await self._authenticate(tenant_id)
        await self._persist_token(tenant_id, token)
        return token

    async def check_token(self, tenant_id: str) -> bool:
        try:
            token = await self.get_valid_token(tenant_id)
        except DefontanaAuthError:
            return False
        if settings.defontana_mock:
            return bool(token)
        connection = await self._get_connection(tenant_id)
        base_url = (connection or {}).get("base_url") or settings.defontana_base_url
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{base_url}/Auth/check",
                    headers={"Authorization": f"Bearer {token}"},
                )
                return resp.status_code == 200
        except httpx.HTTPError as exc:
            logger.warning("Defontana token check failed: %s", exc)
            return False

    async def _authenticate(self, tenant_id: str) -> str:
        if settings.defontana_mock:
            return f"MOCK-TOKEN-{tenant_id}"

        connection = await self._get_connection(tenant_id)
        if not connection:
            raise DefontanaAuthError("Defontana connection is not configured for this tenant")

        base_url = connection.get("base_url") or settings.defontana_base_url
        auth_mode = connection.get("auth_mode", ErpAuthMode.CLIENT_COMPANY_USER.value)

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                if auth_mode == ErpAuthMode.EMAIL_LOGIN.value:
                    params = {
                        "email": connection.get("email"),
                        "password": decrypt_secret(connection.get("email_password_encrypted", "")),
                    }
                    resp = await client.get(f"{base_url}/auth/emailLogin", params=params)
                else:
                    params = {
                        "client": connection.get("client"),
                        "company": connection.get("company"),
                        "user": connection.get("user"),
                        "password": decrypt_secret(connection.get("password_encrypted", "")),
                    }
                    resp = await client.get(f"{base_url}/auth", params=params)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            raise DefontanaAuthError(f"Defontana authentication failed: {exc}") from exc

        token = (
            data.get("access_token")
            or data.get("token")
            or data.get("Token")
            or data.get("AccessToken")
        )
        if not token:
            raise DefontanaAuthError("Defontana auth response did not contain a token")
        return token

    async def _persist_token(self, tenant_id: str, token: str) -> None:
        db = get_database()
        now = now_utc()
        await db[Collections.ERP_TOKENS].update_one(
            {"tenant_id": tenant_id, "erp": self.erp},
            {
                "$set": {
                    "tenant_id": tenant_id,
                    "erp": self.erp,
                    "access_token_encrypted": encrypt_secret(token),
                    "token_type": "Bearer",
                    "expires_at": now + timedelta(minutes=TOKEN_TTL_MINUTES),
                    "last_regained_at": now,
                    "status": ErpTokenStatus.ACTIVE.value,
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
