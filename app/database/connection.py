from sqlalchemy import create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import os
# Cargar variables desde .env
load_dotenv()

# Obtener la URL desde .env o variables del sistema si las hay
raw_url = os.getenv("DATABASE_URL")

if not raw_url:
    raise ValueError("❌ DATABASE_URL no está definida. Asegúrate de tener un archivo .env")

# Render entrega "postgres://"
# SQLAlchemy necesita "postgresql+psycopg2://"
if raw_url.startswith("postgres://"):
    raw_url = raw_url.replace("postgres://", "postgresql+psycopg2://", 1)

#DATABASE_URL=postgresql+psycopg2://postgres:admin@localhost:5432/appalta2
DATABASE_URL = raw_url


engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit = False, autoflush=False, bind = engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()