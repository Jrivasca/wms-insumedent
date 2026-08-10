from enum import Enum


class DispatchStatus(str, Enum):
    PENDING = "pending"
    SENT_TO_DEFONTANA = "sent_to_defontana"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"
