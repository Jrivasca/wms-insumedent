from enum import Enum


class PackingTaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    OBSERVED = "observed"
    CANCELLED = "cancelled"


class PackingLineStatus(str, Enum):
    PENDING = "pending"
    PACKED = "packed"
    PARTIAL = "partial"
