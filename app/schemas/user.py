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