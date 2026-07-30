from sqlalchemy import Column, Integer, String, DateTime, Boolean, BigInteger, Numeric, func
from app.database.connection import Base
from datetime import datetime, timezone 

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
    created_at = Column(
    DateTime(timezone=True),
    server_default=func.now(),
    nullable=False)