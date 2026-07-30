from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    String,
    Text
)

from sqlalchemy.sql import func

from app.database.connection import Base

class StationEvent(Base):

    __tablename__ = "station_events"

    id = Column(
        BigInteger,
        primary_key=True
    )

    station_id = Column(
        BigInteger,
        ForeignKey("stations.id"),
        nullable=False
    )

    measurement_id = Column(
        BigInteger,
        ForeignKey("station_measurements.id"),
        nullable=True
    )

    event_timestamp = Column(
        BigInteger,
        nullable=False
    )

    event_type = Column(
        String(100),
        nullable=False
    )

    event_message = Column(
        Text,
        nullable=True
    )

    created_at = Column(
        DateTime,
        server_default=func.now(),
        nullable=False
    )