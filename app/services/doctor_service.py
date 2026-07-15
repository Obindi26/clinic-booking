from sqlalchemy.orm import Session
from app.models.doctor import Doctor
from app.models.working_day import DoctorWorkingDay
from app.schemas.doctor import DoctorCreate


def create_doctor(db: Session, data: DoctorCreate) -> Doctor:
    doctor = Doctor(
        full_name=data.full_name,
        email=data.email,
        working_hours_start=data.working_hours_start,
        working_hours_end=data.working_hours_end,
    )
    db.add(doctor)
    db.flush()  # get doctor.id before adding working days

    for day in data.working_days:
        db.add(DoctorWorkingDay(doctor_id=doctor.id, day_of_week=day))

    db.flush()
    db.refresh(doctor)
    return doctor


def list_doctors(db: Session) -> list[Doctor]:
    return db.query(Doctor).all()


def get_doctor(db: Session, doctor_id: int) -> Doctor | None:
    return db.get(Doctor, doctor_id)
