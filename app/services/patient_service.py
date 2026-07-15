from sqlalchemy.orm import Session
from app.models.patient import Patient
from app.schemas.patient import PatientCreate


def create_patient(db: Session, data: PatientCreate) -> Patient:
    patient = Patient(
        full_name=data.full_name,
        email=data.email,
        phone=data.phone,
    )
    db.add(patient)
    db.flush()
    db.refresh(patient)
    return patient


def list_patients(db: Session) -> list[Patient]:
    return db.query(Patient).all()


def get_patient(db: Session, patient_id: int) -> Patient | None:
    return db.get(Patient, patient_id)
