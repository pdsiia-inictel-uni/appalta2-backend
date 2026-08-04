from locale import normalize

from fastapi_mail import FastMail, MessageSchema, ConnectionConfig
from pydantic import EmailStr
import asyncio
import resend
import hmac
import hashlib
from decimal import Decimal

from app.schemas.station_measurement import StationMeasurementRequest
from app.config.config import mail_conf
#resend.api_key = "re_LFfxqjJa_2Tmm2XnjbWKAkefbVWoasCLd"

# bllf wqlj nukv tuzg
# conf = ConnectionConfig(
#     MAIL_USERNAME="anthonymig1@gmail.com",
#     MAIL_PASSWORD="bllfwqljnukvtuzg",
#     MAIL_FROM="anthonymig1@gmail.com",
#     MAIL_PORT=587,
#     MAIL_SERVER="smtp.gmail.com",
#     MAIL_STARTTLS=True,
#     MAIL_SSL_TLS=False,
#     USE_CREDENTIALS=True
# )

async def send_password_reset_email(to: EmailStr, reset_link: str):
    resend.Emails.send({
    "from": "onboarding@resend.dev",
    "to": to,
    "subject": "Recupera tu contraseña - Appalta2",
    "html": f"""
        <html>
        <body style="font-family: Arial; text-align: center;">
            <h2 style="color:#388E3C;">🔑 Recuperación de contraseña</h2>
            <p>Hemos recibido una solicitud para restablecer tu contraseña.</p>
            <p>Haz clic en el siguiente botón:</p>
            <a href="{reset_link}" 
               style="background-color:#4CAF50; color:white; padding:10px 20px;
                      text-decoration:none; border-radius:8px;">Restablecer Contraseña</a>
            <p style="color:gray; font-size:12px; margin-top:20px;">
            Si no solicitaste esto, puedes ignorar este correo.
            </p>
        </body>
        </html>
        """
    })

async def send_password_reset_email_gmail(to: EmailStr, reset_link: str):
    
    message = MessageSchema(
        subject="Recupera tu contraseña - Appalta2",
        recipients=[to],
        body=f"""
        <html>
        <body style="font-family: Arial; text-align: center;">
            <h2 style="color:#388E3C;">🔑 Recuperación de contraseña</h2>
            <p>Hemos recibido una solicitud para restablecer tu contraseña.</p>
            <p>Haz clic en el siguiente botón:</p>
            <a href="{reset_link}" 
               style="background-color:#4CAF50; color:white; padding:10px 20px;
                      text-decoration:none; border-radius:8px;">Restablecer Contraseña</a>
            <p style="color:gray; font-size:12px; margin-top:20px;">
            Si no solicitaste esto, puedes ignorar este correo.
            </p>
        </body>
        </html>
        """,
        subtype="html"
    )
    fm = FastMail(mail_conf)
    await fm.send_message(message)


async def send_verification_email(to: EmailStr, verification_link: str):
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{
                background-color: #f3f6f4;
                font-family: 'Segoe UI', Roboto, sans-serif;
                color: #333;
                margin: 0;
                padding: 0;
            }}
            .container {{
                max-width: 600px;
                background: #ffffff;
                margin: 40px auto;
                border-radius: 16px;
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
                overflow: hidden;
            }}
            .header {{
                background: linear-gradient(135deg, #2E7D32, #66BB6A);
                padding: 24px;
                text-align: center;
                color: white;
            }}
            .header h1 {{
                margin: 0;
                font-size: 24px;
                font-weight: 600;
            }}
            .content {{
                padding: 32px 40px;
                text-align: center;
            }}
            .content p {{
                font-size: 16px;
                color: #444;
                line-height: 1.6;
                margin-bottom: 16px;
            }}
            .button {{
                display: inline-block;
                background: #43A047;
                color: white;
                padding: 14px 28px;
                margin: 24px 0;
                text-decoration: none;
                border-radius: 8px;
                font-weight: 600;
                transition: background 0.3s ease;
                font-size: 16px;
            }}
            .button:hover {{
                background: #388E3C;
            }}
            .footer {{
                background: #f0f0f0;
                padding: 18px;
                text-align: center;
                font-size: 13px;
                color: #666;
            }}
            .leaf-image {{
                width: 100%;
                height: 180px;
                object-fit: cover;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>Appalta2 🌿</h1>
                <p>Diagnóstico inteligente de hojas de palta Hass</p>
            </div>
            <div class="content">
                <p>¡Hola!</p>
                <p>Gracias por registrarte en <strong>Appalta2</strong>, la aplicación que te ayuda a analizar el estado de salud de tus hojas de palta.</p>
                <p>Antes de comenzar, por favor verifica tu correo electrónico haciendo clic en el siguiente botón:</p>
                <a href="{verification_link}" class="button">Verificar mi correo</a>
                <p>Si no solicitaste esta cuenta, puedes ignorar este mensaje.</p>
            </div>
            <div class="footer">
                © 2025 Appalta2 · Diagnóstico inteligente de hojas de palta Hass
            </div>
        </div>
    </body>
    </html>
    """

    resend.Emails.send({
    "from": "onboarding@resend.dev",
    "to": to,
    "subject": "🌿 Verifica tu correo electrónico - Appalta2",
    "html": html
    })

async def send_verification_email_gmail(to: EmailStr, verification_link: str):
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{
                background-color: #f3f6f4;
                font-family: 'Segoe UI', Roboto, sans-serif;
                color: #333;
                margin: 0;
                padding: 0;
            }}
            .container {{
                max-width: 600px;
                background: #ffffff;
                margin: 40px auto;
                border-radius: 16px;
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
                overflow: hidden;
            }}
            .header {{
                background: linear-gradient(135deg, #2E7D32, #66BB6A);
                padding: 24px;
                text-align: center;
                color: white;
            }}
            .header h1 {{
                margin: 0;
                font-size: 24px;
                font-weight: 600;
            }}
            .content {{
                padding: 32px 40px;
                text-align: center;
            }}
            .content p {{
                font-size: 16px;
                color: #444;
                line-height: 1.6;
                margin-bottom: 16px;
            }}
            .button {{
                display: inline-block;
                background: #43A047;
                color: white;
                padding: 14px 28px;
                margin: 24px 0;
                text-decoration: none;
                border-radius: 8px;
                font-weight: 600;
                transition: background 0.3s ease;
                font-size: 16px;
            }}
            .button:hover {{
                background: #388E3C;
            }}
            .footer {{
                background: #f0f0f0;
                padding: 18px;
                text-align: center;
                font-size: 13px;
                color: #666;
            }}
            .leaf-image {{
                width: 100%;
                height: 180px;
                object-fit: cover;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>Appalta2 🌿</h1>
                <p>Diagnóstico inteligente de hojas de palta Hass</p>
            </div>
            <div class="content">
                <p>¡Hola!</p>
                <p>Gracias por registrarte en <strong>Appalta2</strong>, la aplicación que te ayuda a analizar el estado de salud de tus hojas de palta.</p>
                <p>Antes de comenzar, por favor verifica tu correo electrónico haciendo clic en el siguiente botón:</p>
                <a href="{verification_link}" class="button">Verificar mi correo</a>
                <p>Si no solicitaste esta cuenta, puedes ignorar este mensaje.</p>
            </div>
            <div class="footer">
                © 2025 Appalta2 · Diagnóstico inteligente de hojas de palta Hass
            </div>
        </div>
    </body>
    </html>
    """

    message = MessageSchema(
        subject="🌿 Verifica tu correo electrónico - Appalta2",
        recipients=[to],
        body=html,
        subtype="html"
    )

    fm = FastMail(mail_conf)
    await fm.send_message(message)
    print(f"✅ Correo de verificación enviado correctamente a {to}")

from fastapi.responses import HTMLResponse

def invalid_link_page():
    html_content = """
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Enlace inválido - Appalta2</title>
        <style>
            body {
                font-family: 'Segoe UI', sans-serif;
                background: linear-gradient(135deg, #c8e6c9, #a5d6a7);
                display: flex;
                align-items: center;
                justify-content: center;
                height: 100vh;
                margin: 0;
            }
            .card {
                background-color: white;
                padding: 40px;
                border-radius: 20px;
                box-shadow: 0 6px 14px rgba(0,0,0,0.15);
                text-align: center;
                width: 90%;
                max-width: 420px;
                animation: fadeIn 0.5s ease;
            }
            @keyframes fadeIn {
                from { opacity: 0; transform: translateY(20px); }
                to { opacity: 1; transform: translateY(0); }
            }
            h2 {
                color: #c62828;
                margin-bottom: 12px;
            }
            p {
                color: #555;
                font-size: 15px;
                margin-bottom: 24px;
            }
            .icon {
                font-size: 60px;
                color: #e53935;
                margin-bottom: 16px;
            }
            button {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 10px;
                padding: 12px 20px;
                font-size: 16px;
                cursor: pointer;
                transition: background-color 0.3s;
            }
            button:hover {
                background-color: #43a047;
            }
        </style>
    </head>
    <body>
        <div class="card">
            <div class="icon">❌</div>
            <h2>Enlace inválido o expirado</h2>
            <p>El enlace que intentas usar ya no es válido. 
            Es posible que haya expirado o que ya haya sido utilizado.</p>
            <button onclick="window.location.href='/login'">Volver al inicio de sesión</button>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content, status_code=400)

def normalize_empty(value):

    if value is None:
        return "NA"

    return format(
        Decimal(str(value)),
        "f"
    ).rstrip("0").rstrip(".")


def build_message(
    station_code: str,
    data: StationMeasurementRequest
) -> str:

    parts = [

        station_code,

        str(data.timestamp),

        #normalize_empty(data.latitude),

        #normalize_empty(data.longitude),

        normalize_empty(data.battery_level)

    ]

    for measurement in data.measurements:

        parts.append(
            measurement.sensor_code
        )

        parts.append(
            str(normalize_empty(measurement.value))
        )

    return "|".join(parts)

# def build_message(
#     station_id: str,
#     data: StationMeasurementRequest
# ) -> str:

#     return (
#         f"{station_id}|"
#         f"{data.timestamp}|"
#         f"{normalize_empty(data.ambient_temperature)}|"
#         f"{normalize_empty(data.ambient_humidity)}|"
#         f"{normalize_empty(data.atmospheric_pressure)}"
#     )

def verify_signature(
    message: str,
    secret_key: str,
    received_signature: str
) -> bool:

    expected_signature = hmac.new(
        secret_key.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(
        expected_signature,
        received_signature
    )

def to_float(value):

    if value is None:
        return None

    return float(value)

if __name__ == "__main__":
    verification_link = "http://192.168.18.22:8000/verify/abc123"
    asyncio.run(send_verification_email("anthonymig1777@gmail.com", verification_link))