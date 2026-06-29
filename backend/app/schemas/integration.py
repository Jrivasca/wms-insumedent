from typing import Optional

from pydantic import BaseModel

from app.models.integration import ErpAuthMode, ErpEnvironment


class DefontanaConfigRequest(BaseModel):
    environment: ErpEnvironment = ErpEnvironment.TEST
    auth_mode: ErpAuthMode = ErpAuthMode.CLIENT_COMPANY_USER
    client: Optional[str] = None
    company: Optional[str] = None
    user: Optional[str] = None
    password: Optional[str] = None
    email: Optional[str] = None
    email_password: Optional[str] = None
    base_url: Optional[str] = None
