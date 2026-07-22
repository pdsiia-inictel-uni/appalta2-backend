from sqlalchemy import Column, DateTime, BigInteger, Numeric
from app.database.connection import Base
from sqlalchemy import func
from sqlalchemy.orm import relationship
from sqlalchemy import ForeignKey

class StationMeasurement(Base):

    __tablename__ = "station_measurements"

    id = Column(BigInteger, primary_key=True)

    station_id = Column(
        BigInteger,
        ForeignKey("stations.id"),
        nullable=False
    )

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