from datetime import time
from typing import List
from pydantic import BaseModel, EmailStr, field_validator


class DoctorCreate(BaseModel):
    full_name: str
    email: EmailStr
    working_hours_start: time
    working_hours_end: time
    working_days: List[int]  # list of 0-6 integers

    @field_validator("working_days")
    @classmethod
    def validate_days(cls, v: List[int]) -> List[int]:
        if not v:
            raise ValueError("At least one working day is required")
        for d in v:
            if d not in range(7):
                raise ValueError(f"day_of_week must be 0–6, got {d}")
        return list(set(v))  # deduplicate

    @field_validator("working_hours_end")
    @classmethod
    def end_after_start(cls, v: time, info) -> time:
        start = info.data.get("working_hours_start")
        if start and v <= start:
            raise ValueError("working_hours_end must be after working_hours_start")
        return v


class DoctorResponse(BaseModel):
    id: int
    full_name: str
    working_hours_start: time
    working_hours_end: time
    working_days: List[int]

    model_config = {"from_attributes": True}
