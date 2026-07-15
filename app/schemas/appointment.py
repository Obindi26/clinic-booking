from datetime import datetime
from typing import Optional
from pydantic import BaseModel, field_validator
from app.models.appointment import AppointmentStatus


class AppointmentCreate(BaseModel):
    doctor_id: int
    patient_id: int
    slot_time: datetime  # ISO-8601, UTC expected

    @field_validator("slot_time")
    @classmethod
    def must_be_timezone_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError(
                "slot_time must include timezone info (e.g. 2025-07-20T09:00:00Z)"
            )
        return v


class AppointmentResponse(BaseModel):
    id: int
    doctor_id: int
    patient_id: int
    slot_time: datetime
    status: AppointmentStatus
    cancel_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CancelRequest(BaseModel):
    reason: str


class RescheduleRequest(BaseModel):
    new_slot_time: datetime

    @field_validator("new_slot_time")
    @classmethod
    def must_be_timezone_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError(
                "new_slot_time must include timezone info (e.g. 2025-07-20T10:00:00Z)"
            )
        return v


class AvailabilityResponse(BaseModel):
    doctor_id: int
    date: str          # YYYY-MM-DD
    available_slots: list[datetime]
