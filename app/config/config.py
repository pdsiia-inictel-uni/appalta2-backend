import os
from dotenv import load_dotenv
from fastapi_mail import ConnectionConfig

# Carga las variables del archivo .env
load_dotenv()

# Información básica de la aplicación
APP_NAME = os.getenv("APP_NAME", "Appalta2")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
MAX_DRIFT_SECONDS = 300  # 5 minutos
# Configuración de correo
MAIL_USERNAME = os.getenv("MAIL_USERNAME")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
MAIL_FROM = os.getenv("MAIL_FROM", MAIL_USERNAME)
MAIL_PORT = int(os.getenv("MAIL_PORT", 587))
MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.gmail.com")
MAIL_STARTTLS = os.getenv("MAIL_STARTTLS", "True") == "True"
MAIL_SSL_TLS = os.getenv("MAIL_SSL_TLS", "False") == "True"
USE_CREDENTIALS = os.getenv("USE_CREDENTIALS", "True") == "True"

# Configuración para FastAPI-Mail
mail_conf = ConnectionConfig(
    MAIL_USERNAME=MAIL_USERNAME,
    MAIL_PASSWORD=MAIL_PASSWORD,
    MAIL_FROM=MAIL_FROM,
    MAIL_PORT=MAIL_PORT,
    MAIL_SERVER=MAIL_SERVER,
    MAIL_STARTTLS=MAIL_STARTTLS,
    MAIL_SSL_TLS=MAIL_SSL_TLS,
    USE_CREDENTIALS=USE_CREDENTIALS,
)