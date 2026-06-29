from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field

from app.models.user import UserRole


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserPublic(BaseModel):
    id: str
    tenant_id: str
    name: str
    email: str
    role: str
    allowed_warehouse_ids: List[str] = Field(default_factory=list)
    is_active: bool = True


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserPublic


class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str = Field(min_length=4)
    role: UserRole = UserRole.PICKER
    allowed_warehouse_ids: List[str] = Field(default_factory=list)


class UserUpdate(BaseModel):
    name: Optional[str] = None
    password: Optional[str] = Field(default=None, min_length=4)
    role: Optional[UserRole] = None
    allowed_warehouse_ids: Optional[List[str]] = None
    is_active: Optional[bool] = None
