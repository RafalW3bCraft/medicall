"""
Handoffs router.

GET /handoffs — list all pending human-review handoffs
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class HandoffSummary(BaseModel):
    message: str


@router.get("/", response_model=HandoffSummary)
async def list_handoffs() -> HandoffSummary:
    """
    Stub: list all pending handoffs for staff review.
    Full implementation in next iteration.
    """
    return HandoffSummary(message="Handoffs endpoint — implementation in progress.")
