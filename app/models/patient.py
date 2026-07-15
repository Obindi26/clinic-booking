from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship
from app.db.base import Base


class Patient(Base):
    """
    A patient registered in the system.
    Authentication is out of scope for this assessment, but the model is
    structured so a JWT/session layer can be added without schema changes.
    """

    __tablename__ = "patients"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(100), nullable=False)
    email = Column(String(254), nullable=False, unique=True)
    phone = Column(String(30), nullable=True)

    appointments = relationship(
        "Appointment", back_populates="patient", lazy="dynamic"
    )
