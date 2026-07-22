from pydantic import BaseModel, EmailStr, model_validator

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    firstname: str
    father_lastname: str
    mother_lastname: str
    document_of_identity: str
    cellphone: str
 
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

class AgroStationData(BaseModel):
    timestamp: int
    temp_ambiental: float | None = None
    humedad_ambiental: float | None = None
    presion_atmosferica: float | None = None

    @model_validator(mode="after")
    def validate_at_least_one_value(self):
        if (
            self.temp_ambiental is None and
            self.humedad_ambiental is None and
            self.presion_atmosferica is None
        ):
            raise ValueError(
                "Debe enviar al menos una medición"
            )
        return self