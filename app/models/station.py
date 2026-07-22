from sqlalchemy import Column, String, DateTime, BigInteger, Numeric
from app.database.connection import Base
from sqlalchemy import func

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
