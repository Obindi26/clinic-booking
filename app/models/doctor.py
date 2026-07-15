from sqlalchemy import Column, Integer, String, Time
from sqlalchemy.orm import relationship
from app.db.base import Base


class Doctor(Base):
    """
    Represents a clinic doctor.

    working_hours_start / working_hours_end store the doctor's daily schedule
    as plain time values (timezone-naive; interpreted as clinic-local time).
    All datetime comparisons in the service layer convert to UTC before storing.
    """

    __tablename__ = "doctors"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(100), nullable=False)
    # We deliberately do NOT return email/phone in any public API response (PII)
    email = Column(String(254), nullable=False, unique=True)
    # working hours: 24-h clock, e.g. 08:00 – 17:00
    working_hours_start = Column(Time, nullable=False)
    working_hours_end = Column(Time, nullable=False)

    appointments = relationship(
        "Appointment", back_populates="doctor", lazy="dynamic"
    )
    working_days = relationship(
        "DoctorWorkingDay", back_populates="doctor", cascade="all, delete-orphan"
    )
