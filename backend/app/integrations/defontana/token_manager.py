"""Centralized Defontana token management (section 7.1).

Rules enforced here:
- One token per tenant+ERP, stored encrypted in ``erp_tokens``.
- Never request a new token on every call; reuse the stored one until it expires.
- Refresh only when missing/expired (or once on a 401 from a caller).
"""
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import httpx

from app.core.config import settings
from app.core.tenant_db import tenant_db
from app.core.logging import get_logger
from app.core.security import decrypt_secret, encrypt_secret
from app.core.utils import now_utc
from app.models import Collections
from app.models.integration import ErpAuthMode, ErpTokenStatus

logger = get_logger(__name__)

# Fallback TTL when the auth response carries no ``expires_in``.
TOKEN_TTL_MINUTES = 50
# Refresh a little before the real expiry to avoid edge-of-expiry failures.
EXPIRY_MARGIN = timedelta(minutes=5)


class DefontanaAuthError(Exception):
    pass


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    """Motor (sin ``tz_aware``) devuelve los datetimes naive, en UTC: normalizar antes de
    compararlos con ``now_utc()``, que es aware."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class DefontanaTokenManager:
    erp = "defontana"

    async def _get_connection(self, tenant_id: str) -> Optional[dict]:
        db = tenant_db(tenant_id)
        return await db[Collections.ERP_CONNECTIONS].find_one(
            {"tenant_id": tenant_id, "erp": self.erp}
        )

    async def _stored_token(self, tenant_id: str) -> Optional[dict]:
        db = tenant_db(tenant_id)
        return await db[Collections.ERP_TOKENS].find_one(
            {"tenant_id": tenant_id, "erp": self.erp}
        )

    async def get_valid_token(self, tenant_id: str) -> str:
        token_doc = await self._stored_token(tenant_id)
        if token_doc and token_doc.get("expires_at"):
            expires_at = _aware(token_doc["expires_at"])
            if expires_at > now_utc() and token_doc.get("status") == ErpTokenStatus.ACTIVE.value:
                decrypted = decrypt_secret(token_doc.get("access_token_encrypted", ""))
                if decrypted:
                    return decrypted
        return await self.refresh_token(tenant_id)

    async def refresh_token(self, tenant_id: str) -> str:
        token, expires_in = await self._authenticate(tenant_id)
        await self._persist_token(tenant_id, token, expires_in)
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

    async def _authenticate(self, tenant_id: str) -> Tuple[str, Optional[int]]:
        """Devuelve (token, expires_in en segundos si Defontana lo informa)."""
        if settings.defontana_mock:
            return f"MOCK-TOKEN-{tenant_id}", None

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
            message = data.get("message") or "Defontana auth response did not contain a token"
            raise DefontanaAuthError(message)
        try:
            expires_in = int(data.get("expires_in")) if data.get("expires_in") else None
        except (TypeError, ValueError):
            expires_in = None
        return token, expires_in

    async def _persist_token(
        self, tenant_id: str, token: str, expires_in: Optional[int] = None
    ) -> None:
        db = tenant_db(tenant_id)
        now = now_utc()
        if expires_in and timedelta(seconds=expires_in) > EXPIRY_MARGIN * 2:
            ttl = timedelta(seconds=expires_in) - EXPIRY_MARGIN
        else:
            ttl = timedelta(minutes=TOKEN_TTL_MINUTES)
        await db[Collections.ERP_TOKENS].update_one(
            {"tenant_id": tenant_id, "erp": self.erp},
            {
                "$set": {
                    "tenant_id": tenant_id,
                    "erp": self.erp,
                    "access_token_encrypted": encrypt_secret(token),
                    "token_type": "Bearer",
                    "expires_at": now + ttl,
                    "last_regained_at": now,
                    "status": ErpTokenStatus.ACTIVE.value,
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
