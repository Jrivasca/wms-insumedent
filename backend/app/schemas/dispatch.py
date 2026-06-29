from typing import Optional

from pydantic import BaseModel


class DispatchRequest(BaseModel):
    carrier: Optional[str] = None
    tracking_number: Optional[str] = None
