# Import all models here so Alembic / create_all picks them up automatically
from app.models.doctor import Doctor
from app.models.working_day import DoctorWorkingDay
from app.models.patient import Patient
from app.models.appointment import Appointment, AppointmentStatus

__all__ = ["Doctor", "DoctorWorkingDay", "Patient", "Appointment", "AppointmentStatus"]
