"""
Unit tests for the appointment service layer.
All tests run against an in-memory SQLite DB — no Postgres required.
"""

from datetime import datetime, timedelta, timezone, date, time

import pytest

from app.models.appointment import AppointmentStatus
from app.services import appointment_service
from tests.conftest import future_slot, make_doctor, make_patient


# ===========================================================================
# Availability
# ===========================================================================

class TestAvailability:

    def test_returns_slots_within_working_hours(self, db):
        doctor = make_doctor(db, start=time(8, 0), end=time(10, 0))
        # 08:00–10:00 = 4 slots: 08:00, 08:30, 09:00, 09:30
        target_date = date.today() + timedelta(days=1)
        # Ensure it falls on a working day (Mon-Fri)
        while target_date.weekday() > 4:
            target_date += timedelta(days=1)

        slots = appointment_service.get_available_slots(db, doctor.id, target_date)
        assert len(slots) == 4

    def test_booked_slot_not_in_availability(self, db):
        doctor = make_doctor(db, email="avail2@example.com", start=time(8, 0), end=time(10, 0))
        patient = make_patient(db, email="avail2@example.org")

        target_date = date.today() + timedelta(days=2)
        while target_date.weekday() > 4:
            target_date += timedelta(days=1)

        slot = datetime(target_date.year, target_date.month, target_date.day,
                        8, 0, tzinfo=timezone.utc)
        appointment_service.book_appointment(db, doctor.id, patient.id, slot)

        slots = appointment_service.get_available_slots(db, doctor.id, target_date)
        assert slot not in slots

    def test_non_working_day_returns_empty(self, db):
        # Doctor only works Monday (0)
        doctor = make_doctor(db, email="noday@example.com", working_days=[0])
        # Find a Tuesday
        target = date.today() + timedelta(days=1)
        while target.weekday() != 1:
            target += timedelta(days=1)

        slots = appointment_service.get_available_slots(db, doctor.id, target)
        assert slots == []

    def test_unknown_doctor_raises(self, db):
        with pytest.raises(ValueError, match="not found"):
            appointment_service.get_available_slots(db, 99999, date.today())


# ===========================================================================
# Booking
# ===========================================================================

class TestBooking:

    def test_successful_booking(self, db):
        doctor = make_doctor(db, email="book1@example.com")
        patient = make_patient(db, email="book1@example.org")
        slot = future_slot(days_ahead=3)
        while slot.weekday() > 4:
            slot += timedelta(days=1)

        appt = appointment_service.book_appointment(db, doctor.id, patient.id, slot)

        assert appt.id is not None
        assert appt.status == AppointmentStatus.BOOKED
        assert appt.doctor_id == doctor.id
        assert appt.patient_id == patient.id

    def test_duplicate_booking_raises(self, db):
        doctor = make_doctor(db, email="dup@example.com")
        patient = make_patient(db, email="dup@example.org")
        slot = future_slot(days_ahead=4)
        while slot.weekday() > 4:
            slot += timedelta(days=1)

        appointment_service.book_appointment(db, doctor.id, patient.id, slot)

        with pytest.raises(ValueError, match="already booked"):
            appointment_service.book_appointment(db, doctor.id, patient.id, slot)

    def test_slot_in_past_raises(self, db):
        doctor = make_doctor(db, email="past@example.com")
        patient = make_patient(db, email="past@example.org")
        past_slot = datetime(2020, 1, 6, 9, 0, tzinfo=timezone.utc)  # Monday

        with pytest.raises(ValueError, match="1 hour"):
            appointment_service.book_appointment(db, doctor.id, patient.id, past_slot)

    def test_slot_within_1_hour_raises(self, db):
        doctor = make_doctor(db, email="soon@example.com")
        patient = make_patient(db, email="soon@example.org")
        soon = datetime.now(timezone.utc) + timedelta(minutes=30)

        with pytest.raises(ValueError, match="1 hour"):
            appointment_service.book_appointment(db, doctor.id, patient.id, soon)

    def test_slot_outside_working_hours_raises(self, db):
        doctor = make_doctor(db, email="hours@example.com", start=time(8, 0), end=time(12, 0))
        patient = make_patient(db, email="hours@example.org")
        target_date = date.today() + timedelta(days=3)
        while target_date.weekday() > 4:
            target_date += timedelta(days=1)

        late_slot = datetime(target_date.year, target_date.month, target_date.day,
                             14, 0, tzinfo=timezone.utc)

        with pytest.raises(ValueError, match="outside"):
            appointment_service.book_appointment(db, doctor.id, patient.id, late_slot)

    def test_slot_on_non_working_day_raises(self, db):
        doctor = make_doctor(db, email="weekday@example.com", working_days=[0])  # Mon only
        patient = make_patient(db, email="weekday@example.org")

        # Find a Tuesday at least 2 days ahead
        target = date.today() + timedelta(days=2)
        while target.weekday() != 1:
            target += timedelta(days=1)

        slot = datetime(target.year, target.month, target.day, 9, 0, tzinfo=timezone.utc)

        with pytest.raises(ValueError, match="does not work"):
            appointment_service.book_appointment(db, doctor.id, patient.id, slot)

    def test_unaligned_slot_raises(self, db):
        doctor = make_doctor(db, email="align@example.com")
        patient = make_patient(db, email="align@example.org")
        target_date = date.today() + timedelta(days=3)
        while target_date.weekday() > 4:
            target_date += timedelta(days=1)

        # 09:15 is not on the grid
        bad_slot = datetime(target_date.year, target_date.month, target_date.day,
                            9, 15, tzinfo=timezone.utc)

        with pytest.raises(ValueError, match="half-hour"):
            appointment_service.book_appointment(db, doctor.id, patient.id, bad_slot)

    def test_unknown_doctor_raises(self, db):
        patient = make_patient(db, email="nodr@example.org")
        with pytest.raises(ValueError, match="not found"):
            appointment_service.book_appointment(db, 99999, patient.id, future_slot(5))

    def test_unknown_patient_raises(self, db):
        doctor = make_doctor(db, email="nopat@example.com")
        with pytest.raises(ValueError, match="not found"):
            appointment_service.book_appointment(db, doctor.id, 99999, future_slot(5))

    def test_timezone_naive_slot_treated_as_utc(self, db):
        """A naive datetime is normalised to UTC rather than rejected outright."""
        doctor = make_doctor(db, email="naive@example.com")
        patient = make_patient(db, email="naive@example.org")
        target_date = date.today() + timedelta(days=5)
        while target_date.weekday() > 4:
            target_date += timedelta(days=1)

        naive = datetime(target_date.year, target_date.month, target_date.day, 9, 0)
        appt = appointment_service.book_appointment(db, doctor.id, patient.id, naive)
        assert appt.status == AppointmentStatus.BOOKED


# ===========================================================================
# Cancellation
# ===========================================================================

class TestCancellation:

    def _booked(self, db, email_suffix="cancel"):
        doctor = make_doctor(db, email=f"dr_{email_suffix}@example.com")
        patient = make_patient(db, email=f"pt_{email_suffix}@example.org")
        slot = future_slot(days_ahead=5)
        while slot.weekday() > 4:
            slot += timedelta(days=1)
        appt = appointment_service.book_appointment(db, doctor.id, patient.id, slot)
        return appt, slot, doctor

    def test_cancel_booked_appointment(self, db):
        appt, slot, doctor = self._booked(db, "c1")
        cancelled = appointment_service.cancel_appointment(db, appt.id, "Changed my mind")

        assert cancelled.status == AppointmentStatus.CANCELLED
        assert cancelled.cancel_reason == "Changed my mind"

    def test_slot_freed_after_cancel(self, db):
        appt, slot, doctor = self._booked(db, "c2")
        appointment_service.cancel_appointment(db, appt.id, "No longer needed")

        slots = appointment_service.get_available_slots(db, doctor.id, slot.date())
        assert slot in slots

    def test_double_cancel_raises(self, db):
        appt, _, _ = self._booked(db, "c3")
        appointment_service.cancel_appointment(db, appt.id, "First cancel")

        with pytest.raises(ValueError, match="already cancelled"):
            appointment_service.cancel_appointment(db, appt.id, "Second cancel")

    def test_cancel_unknown_appointment_raises(self, db):
        with pytest.raises(LookupError):
            appointment_service.cancel_appointment(db, 99999, "Reason")


# ===========================================================================
# Rescheduling
# ===========================================================================

class TestRescheduling:

    def _booked(self, db, email_suffix="reschedule"):
        doctor = make_doctor(db, email=f"dr_{email_suffix}@example.com")
        patient = make_patient(db, email=f"pt_{email_suffix}@example.org")
        slot = future_slot(days_ahead=5)
        while slot.weekday() > 4:
            slot += timedelta(days=1)
        appt = appointment_service.book_appointment(db, doctor.id, patient.id, slot)
        return appt, slot, doctor, patient

    def test_successful_reschedule(self, db):
        appt, old_slot, doctor, _ = self._booked(db, "r1")
        new_slot = future_slot(days_ahead=6)
        while new_slot.weekday() > 4:
            new_slot += timedelta(days=1)

        rescheduled = appointment_service.reschedule_appointment(db, appt.id, new_slot)

        assert rescheduled.slot_time.replace(tzinfo=timezone.utc) == new_slot or \
               rescheduled.slot_time == new_slot
        assert rescheduled.status == AppointmentStatus.BOOKED

    def test_old_slot_freed_after_reschedule(self, db):
        appt, old_slot, doctor, _ = self._booked(db, "r2")
        new_slot = future_slot(days_ahead=7)
        while new_slot.weekday() > 4:
            new_slot += timedelta(days=1)

        appointment_service.reschedule_appointment(db, appt.id, new_slot)

        free_slots = appointment_service.get_available_slots(db, doctor.id, old_slot.date())
        assert old_slot in free_slots

    def test_reschedule_to_taken_slot_raises(self, db):
        appt, _, doctor, patient = self._booked(db, "r3")

        # Book the target slot with another patient
        other_patient = make_patient(db, email="other_r3@example.org")
        new_slot = future_slot(days_ahead=8)
        while new_slot.weekday() > 4:
            new_slot += timedelta(days=1)
        appointment_service.book_appointment(db, doctor.id, other_patient.id, new_slot)

        with pytest.raises(ValueError, match="already booked"):
            appointment_service.reschedule_appointment(db, appt.id, new_slot)

    def test_reschedule_cancelled_appointment_raises(self, db):
        appt, _, _, _ = self._booked(db, "r4")
        appointment_service.cancel_appointment(db, appt.id, "Cancelled")
        new_slot = future_slot(days_ahead=9)

        with pytest.raises(ValueError, match="cancelled"):
            appointment_service.reschedule_appointment(db, appt.id, new_slot)

    def test_reschedule_unknown_appointment_raises(self, db):
        with pytest.raises(LookupError):
            appointment_service.reschedule_appointment(db, 99999, future_slot(5))


# ===========================================================================
# Patient upcoming appointments
# ===========================================================================

class TestPatientAppointments:

    def test_returns_upcoming_sorted(self, db):
        doctor = make_doctor(db, email="upcoming@example.com")
        patient = make_patient(db, email="upcoming@example.org")

        # Find two distinct future weekdays
        slot_a = future_slot(days_ahead=10)
        while slot_a.weekday() > 4:
            slot_a += timedelta(days=1)

        # slot_b must be a different calendar day than slot_a
        slot_b = slot_a + timedelta(days=1)
        while slot_b.weekday() > 4:
            slot_b += timedelta(days=1)

        # Book out of order to verify sorting
        appointment_service.book_appointment(db, doctor.id, patient.id, slot_b)
        appointment_service.book_appointment(db, doctor.id, patient.id, slot_a)

        appts = appointment_service.get_patient_upcoming_appointments(db, patient.id)
        times = [a.slot_time for a in appts]
        assert times == sorted(times)

    def test_cancelled_not_included(self, db):
        doctor = make_doctor(db, email="upcancel@example.com")
        patient = make_patient(db, email="upcancel@example.org")
        slot = future_slot(days_ahead=12)
        while slot.weekday() > 4:
            slot += timedelta(days=1)

        appt = appointment_service.book_appointment(db, doctor.id, patient.id, slot)
        appointment_service.cancel_appointment(db, appt.id, "Cancelled")

        appts = appointment_service.get_patient_upcoming_appointments(db, patient.id)
        assert appts == []

    def test_unknown_patient_raises(self, db):
        with pytest.raises(ValueError, match="not found"):
            appointment_service.get_patient_upcoming_appointments(db, 99999)
