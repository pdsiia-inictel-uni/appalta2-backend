# Backend Appalta2 (API + asistente IA). Ver DEPLOY.md.
# Misma versión de Python con la que se probó el proyecto.
FROM python:3.11-slim

# Evita archivos .pyc y buffer de logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencias primero: se reutiliza la capa mientras requirements.txt no cambie
COPY requirements.txt .
RUN pip install -r requirements.txt

# Código de la app y scripts del asistente (evaluación contra la BD de producción)
COPY app/ app/
COPY scripts/ scripts/

# Usuario sin privilegios
RUN useradd --create-home --uid 10001 appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

# Salud del proceso (no depende de la BD ni del modelo)
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/', timeout=4)" || exit 1

# Un solo proceso: la memoria de conversación del chat vive en el proceso (ver DEPLOY.md).
# --proxy-headers: detrás del proxy HTTPS de producción.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
