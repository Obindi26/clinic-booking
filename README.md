# Clinic Booking API

A REST API for a small clinic appointment booking system.  
Built with **Python 3.12 · FastAPI · PostgreSQL · SQLAlchemy 2**.

**Deployed URL:** `https://clinic-booking-88fg.onrender.com`

---

## Table of Contents

1. [Section 1 — System Design](#section-1--system-design)
2. [Section 2 — API Reference](#section-2--api-reference)
3. [Section 3 — Deployment & CI/CD](#section-3--deployment--cicd)
4. [Section 4 — AI Reflection](#section-4--ai-reflection)
5. [Running Locally](#running-locally)

---

## Section 1 — System Design

### The Scenario

> "We run a small clinic with 5 doctors. Patients need to book appointments online. Each doctor has set working hours and works in 30-minute slots. A patient should see which slots are free for a given doctor on a given day, pick one, and book it. Once booked, that slot must not be available to others. Patients should also be able to cancel. We're starting small but want to grow."

---

### Core Models

| Model | Purpose |
|---|---|
| `Doctor` | A clinic physician with working hours (`working_hours_start`, `working_hours_end`) |
| `DoctorWorkingDay` | Which days of the week (0=Mon … 6=Sun) a doctor works. Separate table for flexibility |
| `Patient` | A registered patient |
| `Appointment` | A single 30-minute booking linking a doctor, patient, and UTC slot time |

**Appointment status** is an enum (`booked` / `cancelled`) rather than a boolean so future states (e.g. `no_show`, `completed`) can be added without a schema migration.

### Entity Relationship

```
Doctor ──< DoctorWorkingDay
Doctor ──< Appointment >── Patient
```

---

### Key Design Decisions

**1. Slot model: fixed 30-minute grid, not stored rows**

Slots are computed on the fly by the `get_available_slots` service: generate every 30-minute window within a doctor's working hours, then subtract booked ones. This avoids pre-generating thousands of empty slot rows and means the grid adapts automatically if a doctor's hours change. The trade-off is slightly more computation per availability request — acceptable at this scale.

**2. UTC everywhere**

All datetimes are stored in UTC (`DateTime(timezone=True)`). The API accepts and returns ISO-8601 strings with timezone info required. Callers convert clinic-local time to UTC before sending. This avoids DST bugs and is the standard for any system that may serve multiple timezones.

**3. Concurrency safety: two-layer approach**

The most critical correctness requirement is that two concurrent requests cannot double-book the same slot.

- **Layer 1 (application):** `SELECT … FOR UPDATE` acquires a row-level lock before checking availability and inserting. A second concurrent request blocks at the lock until the first transaction commits.
- **Layer 2 (database):** A `UNIQUE constraint on (doctor_id, slot_time)` is the last line of defence. If the application lock is somehow bypassed (e.g. direct DB access, a future bug), the DB rejects the duplicate insert with an `IntegrityError`, which the service catches and surfaces as HTTP 409.

This is the same race condition present in the code review example shown in the assessment — a plain `filter().exists()` followed by a separate `create()` is not atomic.

**4. Reschedule is atomic — patient never loses their slot**

The reschedule operation updates the existing appointment row in-place within a single transaction. The original slot is freed and the new slot is validated and locked in the same transaction. If the new slot is taken, the transaction rolls back and the patient retains their original booking. There is no window where they hold neither slot.

**5. Cancellation uses status, not deletion**

Cancelled appointments are retained in the database for audit purposes. Availability queries filter on `status = 'booked'`, so cancelled slots become bookable again automatically.

**6. 1-hour lead time (bonus)**

All bookings and reschedules require the slot to be at least 1 hour in the future. This is enforced in the service layer so it applies consistently regardless of which endpoint is called.

**7. PII is never returned in API responses**

The `Doctor` model stores `email` for internal use but it is never included in any response schema. This addresses the PII exposure issue present in the code review sample.

**8. Authentication: out of scope, but considered**

The assessment does not require auth. The design is structured so a JWT middleware layer can be added without schema changes — `patient_id` in the booking request would be replaced by the authenticated user's ID from the token. This was a deliberate scope decision, noted here.

---

### Concurrency Edge Cases Considered

| Scenario | Handling |
|---|---|
| Two requests book the same slot simultaneously | `SELECT FOR UPDATE` + `UNIQUE` constraint |
| Doctor's working hours change after bookings exist | Existing appointments are unaffected; new availability queries use the updated hours |
| Doctor cancels an entire day | Not in scope yet; would require a `DoctorLeave` model and filtering in availability |
| Patient reschedules to a taken slot | Transaction rolls back; patient retains original slot |

---

## Section 2 — API Reference

Interactive docs available at `/docs` (Swagger UI) and `/redoc` when running.

### Required Endpoints

#### `POST /appointments` — Book a slot

```json
{
  "doctor_id": 1,
  "patient_id": 1,
  "slot_time": "2025-08-01T09:00:00Z"
}
```

Validates:
- Doctor and patient exist
- Slot falls on one of the doctor's working days
- Slot is within the doctor's working hours
- Slot aligns to the 30-minute grid (xx:00 or xx:30)
- Slot is at least 1 hour in the future *(bonus)*
- Slot is not already booked

Returns `201 Created` with the appointment object.

---

#### `GET /doctors/{id}/availability?date=YYYY-MM-DD` — Available slots

Returns all free 30-minute slots for a doctor on a given date.

```json
{
  "doctor_id": 1,
  "date": "2025-08-01",
  "available_slots": [
    "2025-08-01T08:00:00Z",
    "2025-08-01T08:30:00Z",
    "2025-08-01T09:30:00Z"
  ]
}
```

---

#### `PATCH /appointments/{id}/cancel` — Cancel

```json
{ "reason": "Family emergency" }
```

- Returns `400` if already cancelled.
- Freed slot becomes bookable immediately.

---

#### `PATCH /appointments/{id}/reschedule` — Reschedule

```json
{ "new_slot_time": "2025-08-02T10:00:00Z" }
```

- Validates new slot exactly as a fresh booking.
- Returns `400` if appointment is cancelled.
- Returns `422` if new slot is invalid or taken.
- Original slot is freed atomically — patient never loses both slots.

---

### Bonus Endpoints

#### `GET /patients/{id}/appointments` — Upcoming appointments

Returns upcoming `booked` appointments for a patient, sorted by date ascending.

---

### HTTP Status Codes Used

| Code | Meaning |
|---|---|
| `201` | Resource created |
| `200` | OK |
| `400` | Business rule violation (e.g. already cancelled) |
| `404` | Doctor / patient / appointment not found |
| `422` | Validation error (bad input, slot taken, outside hours) |

---

### Helper Endpoints (for seeding data)

| Method | Path | Description |
|---|---|---|
| `POST` | `/doctors` | Register a doctor |
| `GET` | `/doctors` | List all doctors |
| `GET` | `/doctors/{id}` | Get a doctor |
| `POST` | `/patients` | Register a patient |
| `GET` | `/patients` | List all patients |
| `GET` | `/health` | Health check |

---

## Section 3 — Deployment & CI/CD

### Deployed Application

**Public URL:** `https://clinic-booking-88fg.onrender.com`  
**Docs:** `https://clinic-booking-88fg.onrender.com/docs`

**Deployed URL:** `https://clinic-booking-88fg.onrender.com`  
**Docs:** `https://clinic-booking-88fg.onrender.com/docs`

---

### CI/CD Pipeline

**Tool:** GitHub Actions (`.github/workflows/ci.yml`)

**What it does:**

1. **On every pull request to `main`:**
   - Sets up Python 3.12
   - Installs `requirements-dev.txt`
   - Runs the full test suite (`pytest tests/ --cov=app`)
   - The PR is blocked from merging if tests fail

2. **On merge (push) to `main`:**
   - Runs tests first (same job, must pass)
   - Deploys to Railway using the Railway CLI and `RAILWAY_TOKEN` secret
   - Deployment is skipped if tests fail

**Deployment trigger:** merging any PR into `main`.

**Required GitHub secret:** `RAILWAY_TOKEN` — generate from [railway.app/account/tokens](https://railway.app/account/tokens) and add under _Settings → Secrets → Actions_.

**Railway config:** `railway.toml` at the repo root tells Railway to build from the `Dockerfile` and use `/health` as the healthcheck endpoint.

---

### Running Locally

#### Option A — Docker Compose (recommended)

```bash
git clone <your-repo-url>
cd clinic-booking
docker compose up --build
```

API available at `http://localhost:8000/docs`

#### Option B — Plain Python

```bash
git clone <your-repo-url>
cd clinic-booking

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

# Start a Postgres instance (or use the Docker one)
docker run -d -p 5432:5432 \
  -e POSTGRES_USER=clinic \
  -e POSTGRES_PASSWORD=clinic \
  -e POSTGRES_DB=clinic_booking \
  postgres:16-alpine

cp .env.example .env
# Edit .env and set DATABASE_URL if needed

uvicorn app.main:app --reload
```

#### Running Tests

```bash
# No Postgres needed — tests use SQLite in-memory
TESTING=1 pytest tests/ -v --cov=app
```

#### Seeding Sample Data

```bash
# Create a doctor
curl -X POST http://localhost:8000/doctors \
  -H "Content-Type: application/json" \
  -d '{
    "full_name": "Dr. Alice Mwangi",
    "email": "alice@clinic.example.com",
    "working_hours_start": "08:00:00",
    "working_hours_end": "17:00:00",
    "working_days": [0, 1, 2, 3, 4]
  }'

# Create a patient
curl -X POST http://localhost:8000/patients \
  -H "Content-Type: application/json" \
  -d '{
    "full_name": "James Kamau",
    "email": "james@example.com",
    "phone": "+254700000001"
  }'

# Check availability (use a future Monday date)
curl "http://localhost:8000/doctors/1/availability?date=2025-08-04"

# Book an appointment
curl -X POST http://localhost:8000/appointments \
  -H "Content-Type: application/json" \
  -d '{
    "doctor_id": 1,
    "patient_id": 1,
    "slot_time": "2025-08-04T09:00:00Z"
  }'
```

---

## Section 4 — AI Reflection

### 1. What did I use AI for across the four sections?

- **Section 1 (Design):** Used AI to pressure-test my slot model decision (fixed grid vs. stored rows) and to think through the concurrency edge cases. Asked it to argue the opposing view so I could evaluate both sides.
- **Section 2 (Implementation):** Used AI to generate boilerplate — SQLAlchemy model stubs, Pydantic schema skeletons, FastAPI router structure. Also used it to draft the `select_for_update` pattern and double-check the SQLAlchemy 2.0 syntax for `with_for_update()`.
- **Section 3 (CI/CD):** Used AI to generate the GitHub Actions YAML skeleton and the Railway CLI deploy step syntax, then edited it to match the actual project structure.
- **Section 4 (Tests):** Used AI to suggest edge cases I might have missed (e.g. naive datetime handling, reschedule-to-same-slot, slot that ends exactly at working hours boundary).

### 2. One example where AI improved my work

**Prompt:** "I have a reschedule endpoint. The original slot should be freed and the new one booked atomically. What's the safest way to implement this in SQLAlchemy without a delete-then-insert?"

**AI suggestion:** Update the existing appointment row in-place rather than deleting and re-creating it. This keeps the appointment ID stable (no broken references), is a single row write, and the transaction rollback naturally undoes it if the new slot validation fails.

I had initially planned a delete + insert approach. The in-place update is cleaner and the AI's reasoning about referential stability was correct. I adopted it.

### 3. One example where AI output was wrong

When I asked AI to generate the concurrency test, it produced a test that tried to simulate two concurrent requests using Python threads sharing the same SQLAlchemy session. This is not valid — SQLAlchemy sessions are not thread-safe. The test would have produced misleading results (either false passes or cryptic errors depending on timing).

I caught this because I know sessions are not thread-safe by design. I replaced the concurrent test with a more honest approach: test that the `UNIQUE` constraint is honoured by the SQLite in-memory DB (which it is), and document clearly in the test file that `select_for_update()` is a no-op in SQLite but the constraint still provides the correctness guarantee. The real concurrency protection is verified by the fact that the constraint exists and the service catches `IntegrityError`.

### 4. Two decisions I made without AI

**Decision 1: Status enum instead of a `cancelled` boolean**

I chose an enum (`booked` / `cancelled`) over a simple `cancelled = BooleanField` from the start. AI tools tend to generate the boolean because it matches the simplest reading of the spec. I knew from experience that appointment systems always grow new states — `no_show`, `completed`, `pending_confirmation` — and that migrating a boolean to an enum later is painful. I made this call on day one without prompting an AI, because it's a judgment call rooted in having seen this pattern go wrong before.

**Decision 2: Separating `DoctorWorkingDay` into its own table**

The simplest approach would be a `working_days` integer array column on `Doctor` (supported natively in Postgres). AI would likely suggest this. I separated it into a join table because it leaves the door open for per-day schedule variations (e.g. different hours on Fridays) without a schema change, and it's more queryable. The trade-off is a slightly more complex join — worth it for a system "starting small but wanting to grow." This was my own architectural judgment, not an AI suggestion.
