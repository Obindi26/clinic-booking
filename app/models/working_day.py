from sqlalchemy import Column, Integer, ForeignKey, SmallInteger, UniqueConstraint
from sqlalchemy.orm import relationship
from app.db.base import Base


class DoctorWorkingDay(Base):
    """
    Which days of the week a doctor works.
    day_of_week: 0 = Monday … 6 = Sunday  (matches Python's date.weekday())

    Design decision: store working days separately from the Doctor so we can
    model different schedules per day in the future (e.g. shorter Fridays)
    without a schema change.
    """

    __tablename__ = "doctor_working_days"

    id = Column(Integer, primary_key=True, index=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False)
    day_of_week = Column(SmallInteger, nullable=False)  # 0–6

    __table_args__ = (
        UniqueConstraint("doctor_id", "day_of_week", name="uq_doctor_working_day"),
    )

    doctor = relationship("Doctor", back_populates="working_days")
