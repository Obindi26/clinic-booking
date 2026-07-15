"""
Shared pytest fixtures.

We use an in-memory SQLite database for tests so CI needs no external services.
select_for_update() is a no-op in SQLite, which is fine — we test the logic
paths; concurrency guarantees are enforced by the DB-level UNIQUE constraint
which SQLite also honours.
"""

import os
# Must be set BEFORE importing app.main so create_all is skipped
os.environ["TESTING"] = "1"

import pytest
from datetime import date, time, datetime, timezone, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.db.base import Base, get_db
from app.main import app
from app.models.doctor import Doctor
from app.models.working_day import DoctorWorkingDay
from app.models.patient import Patient

# ---------------------------------------------------------------------------
# SQLite test engine
# ---------------------------------------------------------------------------

SQLITE_URL = "sqlite://"   # pure in-memory, wiped after each test session

engine = create_engine(
    SQLITE_URL,
    connect_args={"check_same_thread": False},
)

# SQLite does not enforce foreign keys by default — turn them on
@event.listens_for(engine, "connect")
def set_sqlite_pragma(conn, _):
    conn.execute("PRAGMA foreign_keys=ON")

TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="session", autouse=True)
def create_tables():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def db():
    """Yield a test DB session that is rolled back after each test."""
    connection = engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture()
def client(db):
    """FastAPI TestClient with the DB session overridden to the test session."""

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Reusable data factories
# ---------------------------------------------------------------------------

def make_doctor(
    db,
    full_name="Dr. Alice",
    email="alice@example.com",
    start=time(8, 0),
    end=time(17, 0),
    working_days=None,   # Mon–Fri by default
) -> Doctor:
    if working_days is None:
        working_days = [0, 1, 2, 3, 4]   # Mon=0 … Fri=4
    doctor = Doctor(
        full_name=full_name,
        email=email,
        working_hours_start=start,
        working_hours_end=end,
    )
    db.add(doctor)
    db.flush()
    for day in working_days:
        db.add(DoctorWorkingDay(doctor_id=doctor.id, day_of_week=day))
    db.flush()
    db.refresh(doctor)
    return doctor


def make_patient(db, full_name="Pat Patient", email="pat@example.org") -> Patient:
    patient = Patient(full_name=full_name, email=email)
    db.add(patient)
    db.flush()
    db.refresh(patient)
    return patient


def future_slot(days_ahead: int = 2, hour: int = 9, minute: int = 0) -> datetime:
    """Return a UTC-aware datetime guaranteed to be in the future (>1 h from now)."""
    target = date.today() + timedelta(days=days_ahead)
    return datetime(target.year, target.month, target.day, hour, minute, 0,
                    tzinfo=timezone.utc)
