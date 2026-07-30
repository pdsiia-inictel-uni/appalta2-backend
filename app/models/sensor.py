from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    String
)

from sqlalchemy.sql import func

from app.database.connection import Base


class Sensor(Base):

    __tablename__ = "sensors"

    id = Column(
        BigInteger,
        primary_key=True
    )

    sensor_code = Column(
        String(100),
        nullable=False,
        unique=True
    )

    sensor_name = Column(
        String(200),
        nullable=False
    )

    unit = Column(
        String(50),
        nullable=True
    )

    created_at = Column(
        DateTime,
        server_default=func.now(),
        nullable=False
    )

    updated_at = Column(
        DateTime,
        server_default=func.now(),
        nullable=False
    )