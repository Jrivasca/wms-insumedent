from enum import Enum


class UserRole(str, Enum):
    ADMIN = "admin"
    SUPERVISOR = "supervisor"
    PICKER = "picker"
    PACKER = "packer"
    RECEIVER = "receiver"
    AUDITOR = "auditor"


ALL_ROLES = [r.value for r in UserRole]

# Roles that may perform supervisor-level approvals (adjustments, partial picking,
# packing differences).
SUPERVISOR_ROLES = {UserRole.ADMIN.value, UserRole.SUPERVISOR.value}
