"""
Appointment service — all booking logic lives here, not in routers.

Concurrency strategy
--------------------
1. We wrap every write operation in db.begin() (atomic transaction).
2. Before inserting, we SELECT … FOR UPDATE on the conflicting row (if any).
   This acquires a row-level lock so a second concurrent request is blocked
   until the first transaction commits/rolls back.
3. As a final backstop the DB has a UNIQUE constraint on (doctor_id, slot_time);
   even if the application lock were bypassed, the DB rejects the duplicate
   with an IntegrityError which we surface as HTTP 409.

Timezone convention
-------------------
All datetimes are stored and compared as UTC.
The helper _to_utc() normalises naive datetimes (assumed UTC) and converts
any tz-aware datetimes to UTC before use.
"""

from datetime import date, datetime, time, timedelta, timezone
from typing import List

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.appointment import Appointment, AppointmentStatus
from app.models.doctor import Doctor
from app.models.patient import Patient
from app.models.working_day import DoctorWorkingDay


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _to_utc(dt: datetime) -> datetime:
    """Return a UTC-aware datetime regardless of input tz."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _slot_grid(start: time, end: time, on_date: date) -> List[datetime]:
    """
    Generate all 30-minute UTC slot datetimes for a doctor on a given date.
    start/end are naive times treated as clinic-local (UTC for this system).
    """
    slots: List[datetime] = []
    current = datetime.combine(on_date, start, tzinfo=timezone.utc)
    finish = datetime.combine(on_date, end, tzinfo=timezone.utc)
    while current + timedelta(minutes=30) <= finish:
        slots.append(current)
        current += timedelta(minutes=30)
    return slots


# ---------------------------------------------------------------------------
# Doctor helpers
# ---------------------------------------------------------------------------

def get_doctor_or_404(db: Session, doctor_id: int) -> Doctor:
    doctor = db.get(Doctor, doctor_id)
    if not doctor:
        raise ValueError(f"Doctor {doctor_id} not found")
    return doctor


def get_patient_or_404(db: Session, patient_id: int) -> Patient:
    patient = db.get(Patient, patient_id)
    if not patient:
        raise ValueError(f"Patient {patient_id} not found")
    return patient


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------

def get_available_slots(db: Session, doctor_id: int, on_date: date) -> List[datetime]:
    """
    Return all free 30-minute slots for a doctor on a given date.
    A slot is free if no BOOKED appointment exists for it.
    """
    doctor = get_doctor_or_404(db, doctor_id)

    # Check the doctor works on this day of the week
    working_day_ids = [wd.day_of_week for wd in doctor.working_days]
    if on_date.weekday() not in working_day_ids:
        return []

    all_slots = _slot_grid(doctor.working_hours_start, doctor.working_hours_end, on_date)
    if not all_slots:
        return []

    # Fetch booked slots for the day in one query
    day_start = datetime.combine(on_date, time.min, tzinfo=timezone.utc)
    day_end = datetime.combine(on_date, time.max, tzinfo=timezone.utc)

    booked = db.execute(
        select(Appointment.slot_time).where(
            Appointment.doctor_id == doctor_id,
            Appointment.slot_time >= day_start,
            Appointment.slot_time <= day_end,
            Appointment.status == AppointmentStatus.BOOKED,
        )
    ).scalars().all()

    booked_set = {_to_utc(bt) for bt in booked}
    return [s for s in all_slots if s not in booked_set]


# ---------------------------------------------------------------------------
# Book
# ---------------------------------------------------------------------------

def book_appointment(
    db: Session,
    doctor_id: int,
    patient_id: int,
    slot_time: datetime,
) -> Appointment:
    """
    Book a slot. Validates:
      - doctor exists
      - patient exists
      - slot falls on a day the doctor works
      - slot falls within the doctor's working hours
      - slot is aligned to the 30-minute grid
      - slot is not in the past
      - slot is at least 1 hour from now (bonus requirement)
      - slot is not already taken (with DB-level lock)
    """
    slot_utc = _to_utc(slot_time)
    now_utc = datetime.now(timezone.utc)

    # ── 1-hour lead time (bonus) ────────────────────────────────────────────
    if slot_utc <= now_utc + timedelta(hours=1):
        raise ValueError(
            "Appointments must be booked at least 1 hour in advance"
        )

    doctor = get_doctor_or_404(db, doctor_id)
    get_patient_or_404(db, patient_id)

    # ── Working day check ───────────────────────────────────────────────────
    working_day_ids = [wd.day_of_week for wd in doctor.working_days]
    if slot_utc.weekday() not in working_day_ids:
        day_name = slot_utc.strftime("%A")
        raise ValueError(f"Dr. {doctor.full_name} does not work on {day_name}s")

    # ── Working hours check ─────────────────────────────────────────────────
    slot_time_only = slot_utc.time().replace(tzinfo=None)
    if not (doctor.working_hours_start <= slot_time_only < doctor.working_hours_end):
        raise ValueError(
            f"Slot {slot_time_only.strftime('%H:%M')} is outside Dr. {doctor.full_name}'s "
            f"working hours ({doctor.working_hours_start.strftime('%H:%M')}–"
            f"{doctor.working_hours_end.strftime('%H:%M')})"
        )

    # ── 30-minute grid alignment ────────────────────────────────────────────
    if slot_utc.minute % 30 != 0 or slot_utc.second != 0 or slot_utc.microsecond != 0:
        raise ValueError("Slot time must be on the hour or half-hour (e.g. 09:00 or 09:30)")

    # ── Slot must end within working hours ──────────────────────────────────
    slot_end = (datetime.combine(date.today(), slot_time_only) + timedelta(minutes=30)).time()
    if slot_end > doctor.working_hours_end:
        raise ValueError(
            f"Slot starting at {slot_time_only.strftime('%H:%M')} would end after "
            f"working hours ({doctor.working_hours_end.strftime('%H:%M')})"
        )

    # ── Concurrency-safe availability check ────────────────────────────────
    # Lock any existing BOOKED appointment for this (doctor, slot).
    # If no row exists the lock is a no-op; we then insert safely.
    existing = db.execute(
        select(Appointment)
        .where(
            Appointment.doctor_id == doctor_id,
            Appointment.slot_time == slot_utc,
            Appointment.status == AppointmentStatus.BOOKED,
        )
        .with_for_update()
    ).scalar_one_or_none()

    if existing:
        raise ValueError("This slot is already booked")

    appointment = Appointment(
        doctor_id=doctor_id,
        patient_id=patient_id,
        slot_time=slot_utc,
        status=AppointmentStatus.BOOKED,
    )
    db.add(appointment)

    try:
        db.flush()   # push to DB within current transaction; raises IntegrityError on duplicate
    except IntegrityError:
        db.rollback()
        raise ValueError("This slot is already booked (concurrent request)")

    db.refresh(appointment)
    return appointment


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------

def cancel_appointment(db: Session, appointment_id: int, reason: str) -> Appointment:
    """
    Cancel a BOOKED appointment. Returns error if already cancelled.
    The slot becomes available again automatically because we filter on
    status=BOOKED when checking availability.
    """
    appointment = db.execute(
        select(Appointment)
        .where(Appointment.id == appointment_id)
        .with_for_update()
    ).scalar_one_or_none()

    if not appointment:
        raise LookupError(f"Appointment {appointment_id} not found")

    if appointment.status == AppointmentStatus.CANCELLED:
        raise ValueError("Appointment is already cancelled")

    appointment.status = AppointmentStatus.CANCELLED
    appointment.cancel_reason = reason
    db.flush()
    db.refresh(appointment)
    return appointment


# ---------------------------------------------------------------------------
# Reschedule
# ---------------------------------------------------------------------------

def reschedule_appointment(
    db: Session,
    appointment_id: int,
    new_slot_time: datetime,
) -> Appointment:
    """
    Move an appointment to a new slot atomically:
      1. Lock the existing appointment row.
      2. Validate the new slot exactly as book_appointment does.
      3. Lock any conflicting appointment at the new slot.
      4. Update the existing row in-place (no delete/re-insert needed).

    If the new slot is already taken the transaction rolls back and the
    patient retains their original slot — they do NOT lose it.
    """
    new_slot_utc = _to_utc(new_slot_time)
    now_utc = datetime.now(timezone.utc)

    # Lock the appointment being rescheduled
    appointment = db.execute(
        select(Appointment)
        .where(Appointment.id == appointment_id)
        .with_for_update()
    ).scalar_one_or_none()

    if not appointment:
        raise LookupError(f"Appointment {appointment_id} not found")

    if appointment.status == AppointmentStatus.CANCELLED:
        raise ValueError("Cannot reschedule a cancelled appointment")

    # Re-use the same validation logic by calling the booking checks inline
    if new_slot_utc <= now_utc + timedelta(hours=1):
        raise ValueError("New slot must be at least 1 hour from now")

    doctor = get_doctor_or_404(db, appointment.doctor_id)

    working_day_ids = [wd.day_of_week for wd in doctor.working_days]
    if new_slot_utc.weekday() not in working_day_ids:
        day_name = new_slot_utc.strftime("%A")
        raise ValueError(f"Dr. {doctor.full_name} does not work on {day_name}s")

    new_slot_time_only = new_slot_utc.time().replace(tzinfo=None)
    if not (doctor.working_hours_start <= new_slot_time_only < doctor.working_hours_end):
        raise ValueError(
            f"New slot {new_slot_time_only.strftime('%H:%M')} is outside working hours"
        )

    if new_slot_utc.minute % 30 != 0 or new_slot_utc.second != 0:
        raise ValueError("New slot time must be on the hour or half-hour")

    slot_end = (
        datetime.combine(date.today(), new_slot_time_only) + timedelta(minutes=30)
    ).time()
    if slot_end > doctor.working_hours_end:
        raise ValueError("New slot would extend beyond working hours")

    # Lock any conflicting booking at the new slot
    conflict = db.execute(
        select(Appointment)
        .where(
            Appointment.doctor_id == appointment.doctor_id,
            Appointment.slot_time == new_slot_utc,
            Appointment.status == AppointmentStatus.BOOKED,
            Appointment.id != appointment_id,   # ignore self
        )
        .with_for_update()
    ).scalar_one_or_none()

    if conflict:
        raise ValueError("The requested new slot is already booked")

    # Move the appointment — original slot freed implicitly
    appointment.slot_time = new_slot_utc
    db.flush()
    db.refresh(appointment)
    return appointment


# ---------------------------------------------------------------------------
# Patient appointments
# ---------------------------------------------------------------------------

def get_patient_upcoming_appointments(
    db: Session,
    patient_id: int,
) -> List[Appointment]:
    """
    Return upcoming BOOKED appointments for a patient, sorted ascending by slot_time.
    """
    get_patient_or_404(db, patient_id)
    now_utc = datetime.now(timezone.utc)

    rows = db.execute(
        select(Appointment)
        .where(
            Appointment.patient_id == patient_id,
            Appointment.status == AppointmentStatus.BOOKED,
            Appointment.slot_time > now_utc,
        )
        .order_by(Appointment.slot_time.asc())
    ).scalars().all()

    return list(rows)
