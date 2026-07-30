from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Numeric
)

from sqlalchemy.sql import func

from app.database.connection import Base


class SensorMeasurement(Base):

    __tablename__ = "sensor_measurements"

    id = Column(
        BigInteger,
        primary_key=True
    )

    measurement_id = Column(
        BigInteger,
        ForeignKey("station_measurements.id"),
        nullable=False
    )

    sensor_id = Column(
        BigInteger,
        ForeignKey("sensors.id"),
        nullable=False
    )

    measurement_timestamp = Column(
        BigInteger,
        nullable=False
    )

    sensor_value = Column(
        Numeric(12, 4),
        nullable=False
    )

    created_at = Column(
        DateTime,
        server_default=func.now(),
        nullable=False
    )