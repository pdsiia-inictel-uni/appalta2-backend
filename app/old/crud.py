from sqlalchemy.orm import Session
from models.user import User
from . import auth, schemas

def get_user_by_email(db: Session, email: str):
    return db.query(User).filter(User.email == email).first()

def get_user_by_token(db: Session, verification_token: str):
    return db.query(User).filter(User.verification_token == verification_token).first()

def get_user_by_reset_password_token(db: Session, reset_password_token: str):
    return db.query(User).filter(User.reset_password_token == reset_password_token).first()

def create_user(db: Session, user: schemas.UserCreate, verification_token: str):
    hashed = auth.hash_password(user.password)
    db_user = User(email = user.email, 
                          firstname = user.firstname,
                          hashed_password = hashed,
                          father_lastname = user.father_lastname,
                          mother_lastname = user.mother_lastname,
                          document_of_identity = user.document_of_identity,
                          cellphone = user.cellphone,
                          is_verified = False,
                          verification_token = verification_token
                          )
    
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


def autenticate_user(db: Session, email: str, password: str):
    user = get_user_by_email(db, email)
    print("autenticate_user user:", user)
    if not user or not auth.verify_password(password, user.hashed_password):
        return None
    return user
0