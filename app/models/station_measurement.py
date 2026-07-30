from sqlalchemy import Column, DateTime, BigInteger, Numeric
from app.database.connection import Base
from sqlalchemy import func
from sqlalchemy import ForeignKey

class StationMeasurement(Base):

    __tablename__ = "station_measurements"

    id = Column(
        BigInteger,
        primary_key=True
    )

    station_id = Column(
        BigInteger,
        ForeignKey("stations.id"),
        nullable=False
    )

    measurement_timestamp = Column(
        BigInteger,
        nullable=False
    )

    latitude = Column(
        Numeric(10, 7),
        nullable=True
    )

    longitude = Column(
        Numeric(10, 7),
        nullable=True
    )

    battery_level = Column(
        Numeric(5, 2),
        nullable=True
    )

    received_at = Column(
        DateTime,
        server_default=func.now(),
        nullable=False
    )