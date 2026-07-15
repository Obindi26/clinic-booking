"""
Clinic Booking API — entry point.

Run locally:
    uvicorn app.main:app --reload

Docs available at:
    http://localhost:8000/docs   (Swagger UI)
    http://localhost:8000/redoc
"""

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.db.base import Base, engine
from app.routers import appointments, doctors, patients


def _create_tables() -> None:
    """Create tables only when running for real (not during test collection)."""
    import os
    # Tests override the engine via dependency injection — skip create_all there
    if os.getenv("TESTING") == "1":
        return
    try:
        Base.metadata.create_all(bind=engine)
    except Exception:
        # Don't crash if DB is unreachable at import time (e.g. CI without Postgres)
        pass


_create_tables()

app = FastAPI(
    title="Clinic Booking API",
    description=(
        "REST API for a small clinic appointment booking system. "
        "Supports booking, cancellation, rescheduling, and availability checks."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(doctors.router)
app.include_router(patients.router)
app.include_router(appointments.router)   # no prefix — /appointments lives at root


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health", tags=["health"], summary="Health check")
def health_check():
    """Returns 200 OK when the service is up. Used by CI/CD and load balancers."""
    return JSONResponse(content={"status": "ok"})


@app.get("/", tags=["health"], include_in_schema=False)
def root():
    return {"message": "Clinic Booking API — visit /docs for interactive documentation"}
