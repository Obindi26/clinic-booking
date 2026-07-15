"""
Integration tests for the HTTP API layer.
Uses the FastAPI TestClient with the in-memory SQLite DB from conftest.
"""

from datetime import datetime, timedelta, timezone, date, time

import pytest

from tests.conftest import future_slot, make_doctor, make_patient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def iso(dt: datetime) -> str:
    return dt.isoformat()


def next_weekday(days_ahead: int = 3) -> datetime:
    """Return a future Monday–Friday 09:00 UTC slot."""
    slot = future_slot(days_ahead=days_ahead)
    while slot.weekday() > 4:
        slot += timedelta(days=1)
    return slot


# ===========================================================================
# Health check
# ===========================================================================

def test_health_check(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ===========================================================================
# Doctor endpoints
# ===========================================================================

class TestDoctorAPI:

    def test_create_doctor(self, client):
        payload = {
            "full_name": "Dr. Bob",
            "email": "bob@example.com",
            "working_hours_start": "08:00:00",
            "working_hours_end": "17:00:00",
            "working_days": [0, 1, 2, 3, 4],
        }
        r = client.post("/doctors", json=payload)
        assert r.status_code == 201
        data = r.json()
        assert data["full_name"] == "Dr. Bob"
        # PII (email) must NOT appear in response
        assert "email" not in data

    def test_list_doctors(self, client, db):
        make_doctor(db, email="list@example.com")
        r = client.get("/doctors")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_get_unknown_doctor_returns_404(self, client):
        r = client.get("/doctors/99999")
        assert r.status_code == 404


# ===========================================================================
# Appointment endpoints
# ===========================================================================

class TestAppointmentAPI:

    def test_book_appointment_success(self, client, db):
        doctor = make_doctor(db, email="apibo@example.com")
        patient = make_patient(db, email="apibo@example.org")
        slot = next_weekday(3)

        r = client.post("/appointments", json={
            "doctor_id": doctor.id,
            "patient_id": patient.id,
            "slot_time": iso(slot),
        })
        assert r.status_code == 201
        data = r.json()
        assert data["status"] == "booked"
        assert data["doctor_id"] == doctor.id

    def test_book_duplicate_returns_422(self, client, db):
        doctor = make_doctor(db, email="apidup@example.com")
        patient = make_patient(db, email="apidup@example.org")
        slot = next_weekday(4)

        client.post("/appointments", json={
            "doctor_id": doctor.id, "patient_id": patient.id, "slot_time": iso(slot),
        })
        r = client.post("/appointments", json={
            "doctor_id": doctor.id, "patient_id": patient.id, "slot_time": iso(slot),
        })
        assert r.status_code == 422

    def test_book_past_slot_returns_422(self, client, db):
        doctor = make_doctor(db, email="apipast@example.com")
        patient = make_patient(db, email="apipast@example.org")
        past = datetime(2020, 1, 6, 9, 0, tzinfo=timezone.utc)

        r = client.post("/appointments", json={
            "doctor_id": doctor.id, "patient_id": patient.id, "slot_time": iso(past),
        })
        assert r.status_code == 422

    def test_get_availability(self, client, db):
        doctor = make_doctor(db, email="apiav@example.com", start=time(8, 0), end=time(10, 0))
        target = date.today() + timedelta(days=3)
        while target.weekday() > 4:
            target += timedelta(days=1)

        r = client.get(f"/doctors/{doctor.id}/availability", params={"date": str(target)})
        assert r.status_code == 200
        data = r.json()
        assert data["doctor_id"] == doctor.id
        assert len(data["available_slots"]) == 4   # 08:00, 08:30, 09:00, 09:30

    def test_cancel_appointment(self, client, db):
        doctor = make_doctor(db, email="apican@example.com")
        patient = make_patient(db, email="apican@example.org")
        slot = next_weekday(5)

        book_r = client.post("/appointments", json={
            "doctor_id": doctor.id, "patient_id": patient.id, "slot_time": iso(slot),
        })
        appt_id = book_r.json()["id"]

        r = client.patch(f"/appointments/{appt_id}/cancel",
                         json={"reason": "Family emergency"})
        assert r.status_code == 200
        assert r.json()["status"] == "cancelled"
        assert r.json()["cancel_reason"] == "Family emergency"

    def test_cancel_already_cancelled_returns_400(self, client, db):
        doctor = make_doctor(db, email="apicanx@example.com")
        patient = make_patient(db, email="apicanx@example.org")
        slot = next_weekday(6)

        book_r = client.post("/appointments", json={
            "doctor_id": doctor.id, "patient_id": patient.id, "slot_time": iso(slot),
        })
        appt_id = book_r.json()["id"]

        client.patch(f"/appointments/{appt_id}/cancel", json={"reason": "First"})
        r = client.patch(f"/appointments/{appt_id}/cancel", json={"reason": "Second"})
        assert r.status_code == 400

    def test_reschedule_appointment(self, client, db):
        doctor = make_doctor(db, email="apires@example.com")
        patient = make_patient(db, email="apires@example.org")
        slot = next_weekday(7)

        book_r = client.post("/appointments", json={
            "doctor_id": doctor.id, "patient_id": patient.id, "slot_time": iso(slot),
        })
        appt_id = book_r.json()["id"]

        new_slot = next_weekday(8)
        r = client.patch(f"/appointments/{appt_id}/reschedule",
                         json={"new_slot_time": iso(new_slot)})
        assert r.status_code == 200
        assert r.json()["status"] == "booked"

    def test_reschedule_cancelled_returns_400(self, client, db):
        doctor = make_doctor(db, email="apirescx@example.com")
        patient = make_patient(db, email="apirescx@example.org")
        slot = next_weekday(9)

        book_r = client.post("/appointments", json={
            "doctor_id": doctor.id, "patient_id": patient.id, "slot_time": iso(slot),
        })
        appt_id = book_r.json()["id"]
        client.patch(f"/appointments/{appt_id}/cancel", json={"reason": "Gone"})

        new_slot = next_weekday(10)
        r = client.patch(f"/appointments/{appt_id}/reschedule",
                         json={"new_slot_time": iso(new_slot)})
        assert r.status_code == 400

    def test_patient_appointments(self, client, db):
        doctor = make_doctor(db, email="apipatap@example.com")
        patient = make_patient(db, email="apipatap@example.org")
        slot = next_weekday(11)

        client.post("/appointments", json={
            "doctor_id": doctor.id, "patient_id": patient.id, "slot_time": iso(slot),
        })

        r = client.get(f"/patients/{patient.id}/appointments")
        assert r.status_code == 200
        appts = r.json()
        assert len(appts) == 1
        assert appts[0]["patient_id"] == patient.id

    def test_unknown_appointment_cancel_returns_404(self, client):
        r = client.patch("/appointments/99999/cancel", json={"reason": "Gone"})
        assert r.status_code == 404
