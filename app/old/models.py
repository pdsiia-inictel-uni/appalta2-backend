from sqlalchemy import Column, Integer, String, DateTime, Boolean, BigInteger, Numeric
from .database import Base
from datetime import datetime, timezone 
from sqlalchemy import func
from sqlalchemy.orm import relationship

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index = True)
    email = Column(String, unique= True, index= True, nullable=False)
    hashed_password = Column(String, nullable=False)
    firstname = Column(String, nullable=True)
    father_lastname = Column(String, nullable=True)
    mother_lastname = Column(String, nullable=True)
    document_of_identity = Column(String, nullable=True)
    cellphone = Column(String(20), unique= False, index = True)
    is_verified = Column(Boolean, default=False)
    verification_token = Column(String, nullable=True)
    reset_password_token = Column(String, nullable=True)
    reset_password_token_expiry = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now(timezone.utc), nullable=False)

class Station(Base):
    __tablename__ = "stations"
    id = Column(BigInteger, primary_key=True, index=True)
    station_code = Column(String, unique=True)
    mac_address = Column(String)
    api_key = Column(String)
    secret_key = Column(String)
    last_timestamp = Column(String)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now()
    )

class StationMeasurement(Base):
    __tablename__ = "station_measurements"
    id = Column(BigInteger, primary_key=True)
    measurement_timestamp = Column(BigInteger)
    latitude = Column(Numeric)
    longitude = Column(Numeric)
    battery_level = Column(Numeric)
    ambient_temperature = Column(Numeric)
    ambient_humidity = Column(Numeric)
    atmospheric_pressure = Column(Numeric)
    soil_temperature = Column(Numeric)
    soil_moisture = Column(Numeric)
    soil_ph = Column(Numeric)
    received_at = Column(
        DateTime,
        server_default=func.now()
    )
    station = relationship("Station")
