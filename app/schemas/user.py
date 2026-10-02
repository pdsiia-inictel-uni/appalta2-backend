import re

from pydantic import BaseModel, EmailStr, field_validator, model_validator

DNI_PATTERN = re.compile(r"\d{8}")
CELLPHONE_PATTERN = re.compile(r"\d{9}")


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    firstname: str
    father_lastname: str
    mother_lastname: str
    document_of_identity: str
    cellphone: str

    @field_validator("document_of_identity")
    @classmethod
    def validate_dni(cls, value: str) -> str:
        value = value.strip()
        if not DNI_PATTERN.fullmatch(value):
            raise ValueError("El número de DNI debe tener exactamente 8 dígitos")
        return value

    @field_validator("cellphone")
    @classmethod
    def validate_cellphone(cls, value: str) -> str:
        value = value.strip()
        if not CELLPHONE_PATTERN.fullmatch(value):
            raise ValueError("El número de celular debe tener exactamente 9 dígitos")
        return value


class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    id: int
    email: EmailStr
    firstname: str

    class Config:
        orm_mode = True

class UserInfo(BaseModel):
    firstname: str
    father_lastname: str
    mother_lastname: str
    email: EmailStr

class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user_info: UserInfo


class ResendVerificationRequest(BaseModel):
    email: EmailStr

class ResetRequest(BaseModel):
    email: EmailStr

class ResetPassword(BaseModel):
    token: str
    new_password: str