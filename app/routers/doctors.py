"""
Doctor management endpoints.
These are admin-style helpers so reviewers can seed data without a separate script.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.schemas.doctor import DoctorCreate, DoctorResponse
from app.services import doctor_service

router = APIRouter(prefix="/doctors", tags=["doctors"])


@router.post(
    "",
    response_model=DoctorResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new doctor",
)
def create_doctor(payload: DoctorCreate, db: Session = Depends(get_db)):
    try:
        doctor = doctor_service.create_doctor(db, payload)
        db.commit()
        # Build working_days list for response
        doctor_data = DoctorResponse(
            id=doctor.id,
            full_name=doctor.full_name,
            working_hours_start=doctor.working_hours_start,
            working_hours_end=doctor.working_hours_end,
            working_days=[wd.day_of_week for wd in doctor.working_days],
        )
        return doctor_data
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get(
    "",
    response_model=list[DoctorResponse],
    summary="List all doctors",
)
def list_doctors(db: Session = Depends(get_db)):
    doctors = doctor_service.list_doctors(db)
    return [
        DoctorResponse(
            id=d.id,
            full_name=d.full_name,
            working_hours_start=d.working_hours_start,
            working_hours_end=d.working_hours_end,
            working_days=[wd.day_of_week for wd in d.working_days],
        )
        for d in doctors
    ]


@router.get(
    "/{doctor_id}",
    response_model=DoctorResponse,
    summary="Get a single doctor",
)
def get_doctor(doctor_id: int, db: Session = Depends(get_db)):
    doctor = doctor_service.get_doctor(db, doctor_id)
    if not doctor:
        raise HTTPException(status_code=404, detail=f"Doctor {doctor_id} not found")
    return DoctorResponse(
        id=doctor.id,
        full_name=doctor.full_name,
        working_hours_start=doctor.working_hours_start,
        working_hours_end=doctor.working_hours_end,
        working_days=[wd.day_of_week for wd in doctor.working_days],
    )
