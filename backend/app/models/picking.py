from enum import Enum


class PickingTaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"
    COMPLETED = "completed"
    COMPLETED_WITH_DIFFERENCES = "completed_with_differences"
    CANCELLED = "cancelled"


class PickingLineStatus(str, Enum):
    PENDING = "pending"
    PICKED = "picked"
    MISSING = "missing"
    PARTIAL = "partial"
