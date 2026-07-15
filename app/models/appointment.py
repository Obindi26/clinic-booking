import enum
from sqlalchemy import (
    Column, Integer, String, DateTime, ForeignKey,
    Enum as SAEnum, UniqueConstraint, Index
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base import Base


class AppointmentStatus(str, enum.Enum):
    BOOKED = "booked"
    CANCELLED = "cancelled"


class Appointment(Base):
    """
    A single 30-minute booking slot.

    Concurrency safety:
        The UNIQUE constraint on (doctor_id, slot_time) combined with a
        select_for_update() lock in the service layer ensures two concurrent
        requests cannot double-book the same slot.  The DB constraint is the
        last line of defence — even if the application lock is bypassed, the
        database will reject the duplicate insert with an IntegrityError.

    Timezone decision:
        slot_time is stored as UTC (timezone=True).  The API accepts and
        returns ISO-8601 strings; callers are responsible for converting
        clinic-local time to UTC before sending.

    Cancellation:
        We use a status enum rather than a boolean so future states
        (e.g. NO_SHOW, COMPLETED) can be added without a migration.
        cancel_reason is stored for audit purposes.
    """

    __tablename__ = "appointments"

    id = Column(Integer, primary_key=True, index=True)

    doctor_id = Column(
        Integer, ForeignKey("doctors.id", ondelete="RESTRICT"), nullable=False
    )
    patient_id = Column(
        Integer, ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False
    )

    # UTC datetime of the start of the 30-minute slot
    slot_time = Column(DateTime(timezone=True), nullable=False)

    status = Column(
        SAEnum(AppointmentStatus, name="appointment_status"),
        nullable=False,
        default=AppointmentStatus.BOOKED,
        server_default=AppointmentStatus.BOOKED.value,
    )
    cancel_reason = Column(String(500), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    doctor = relationship("Doctor", back_populates="appointments")
    patient = relationship("Patient", back_populates="appointments")

    __table_args__ = (
        # Enforce one booking per (doctor, slot) at DB level — concurrency safety
        UniqueConstraint("doctor_id", "slot_time", name="uq_doctor_slot"),
        # Speed up availability queries
        Index("ix_appointments_doctor_slot", "doctor_id", "slot_time"),
    )
