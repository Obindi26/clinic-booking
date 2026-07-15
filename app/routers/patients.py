"""
Patient management endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.schemas.patient import PatientCreate, PatientResponse
from app.services import patient_service

router = APIRouter(prefix="/patients", tags=["patients"])


@router.post(
    "",
    response_model=PatientResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new patient",
)
def create_patient(payload: PatientCreate, db: Session = Depends(get_db)):
    try:
        patient = patient_service.create_patient(db, payload)
        db.commit()
        return patient
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get(
    "",
    response_model=list[PatientResponse],
    summary="List all patients",
)
def list_patients(db: Session = Depends(get_db)):
    return patient_service.list_patients(db)


@router.get(
    "/{patient_id}",
    response_model=PatientResponse,
    summary="Get a single patient",
)
def get_patient(patient_id: int, db: Session = Depends(get_db)):
    patient = patient_service.get_patient(db, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {patient_id} not found")
    return patient
