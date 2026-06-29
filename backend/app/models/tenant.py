from enum import Enum


class TenantStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
