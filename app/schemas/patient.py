from typing import Optional
from pydantic import BaseModel, EmailStr


class PatientCreate(BaseModel):
    full_name: str
    email: EmailStr
    phone: Optional[str] = None


class PatientResponse(BaseModel):
    id: int
    full_name: str
    email: EmailStr
    phone: Optional[str] = None

    model_config = {"from_attributes": True}
