"""
Appointment endpoints — required + bonus.

POST   /appointments                        — book a slot
GET    /doctors/{id}/availability           — free slots for a doctor on a date
PATCH  /appointments/{id}/cancel            — cancel with reason
PATCH  /appointments/{id}/reschedule        — move to a new slot
GET    /patients/{id}/appointments          — upcoming bookings (bonus)
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.schemas.appointment import (
    AppointmentCreate,
    AppointmentResponse,
    AvailabilityResponse,
    CancelRequest,
    RescheduleRequest,
)
from app.services import appointment_service

router = APIRouter(tags=["appointments"])


# ---------------------------------------------------------------------------
# POST /appointments
# ---------------------------------------------------------------------------

@router.post(
    "/appointments",
    response_model=AppointmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Book an appointment",
)
def book_appointment(
    payload: AppointmentCreate,
    db: Session = Depends(get_db),
):
    """
    Book a 30-minute slot for a patient with a doctor.

    Validations applied:
    - Doctor and patient must exist
    - Slot must fall on one of the doctor's working days
    - Slot must be within the doctor's working hours
    - Slot must align to the 30-minute grid (xx:00 or xx:30)
    - Slot must be at least 1 hour in the future
    - Slot must not already be booked
    """
    try:
        appointment = appointment_service.book_appointment(
            db=db,
            doctor_id=payload.doctor_id,
            patient_id=payload.patient_id,
            slot_time=payload.slot_time,
        )
        db.commit()
        return appointment
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


# ---------------------------------------------------------------------------
# GET /doctors/{doctor_id}/availability
# ---------------------------------------------------------------------------

@router.get(
    "/doctors/{doctor_id}/availability",
    response_model=AvailabilityResponse,
    summary="Get available slots for a doctor on a given date",
)
def get_availability(
    doctor_id: int,
    date: date,                      # query param: ?date=2025-07-20
    db: Session = Depends(get_db),
):
    """
    Returns all free 30-minute slots for the doctor on the given date.
    Pass `date` as a query parameter in YYYY-MM-DD format.
    """
    try:
        slots = appointment_service.get_available_slots(
            db=db,
            doctor_id=doctor_id,
            on_date=date,
        )
        return AvailabilityResponse(
            doctor_id=doctor_id,
            date=str(date),
            available_slots=slots,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


# ---------------------------------------------------------------------------
# PATCH /appointments/{id}/cancel
# ---------------------------------------------------------------------------

@router.patch(
    "/appointments/{appointment_id}/cancel",
    response_model=AppointmentResponse,
    summary="Cancel an appointment",
)
def cancel_appointment(
    appointment_id: int,
    payload: CancelRequest,
    db: Session = Depends(get_db),
):
    """
    Cancel a booked appointment. A reason must be provided.
    Returns HTTP 400 if the appointment is already cancelled.
    The slot becomes available to others immediately.
    """
    try:
        appointment = appointment_service.cancel_appointment(
            db=db,
            appointment_id=appointment_id,
            reason=payload.reason,
        )
        db.commit()
        return appointment
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


# ---------------------------------------------------------------------------
# PATCH /appointments/{id}/reschedule
# ---------------------------------------------------------------------------

@router.patch(
    "/appointments/{appointment_id}/reschedule",
    response_model=AppointmentResponse,
    summary="Reschedule an appointment to a new slot",
)
def reschedule_appointment(
    appointment_id: int,
    payload: RescheduleRequest,
    db: Session = Depends(get_db),
):
    """
    Move an appointment to a new slot.

    - The original slot is freed atomically in the same transaction.
    - The new slot undergoes the same validations as a fresh booking.
    - Returns HTTP 400 if the appointment is cancelled.
    - Returns HTTP 422 if the new slot is invalid or already taken.
    - If the new slot is taken, the patient keeps their original slot (atomic).
    """
    try:
        appointment = appointment_service.reschedule_appointment(
            db=db,
            appointment_id=appointment_id,
            new_slot_time=payload.new_slot_time,
        )
        db.commit()
        return appointment
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        # distinguish "already cancelled" (400) from validation errors (422)
        msg = str(exc)
        if "cancelled" in msg.lower():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=msg)


# ---------------------------------------------------------------------------
# GET /patients/{patient_id}/appointments  (bonus)
# ---------------------------------------------------------------------------

@router.get(
    "/patients/{patient_id}/appointments",
    response_model=list[AppointmentResponse],
    summary="List upcoming appointments for a patient (bonus)",
)
def get_patient_appointments(
    patient_id: int,
    db: Session = Depends(get_db),
):
    """
    Returns all upcoming BOOKED appointments for a patient, sorted by date ascending.
    """
    try:
        return appointment_service.get_patient_upcoming_appointments(
            db=db,
            patient_id=patient_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
