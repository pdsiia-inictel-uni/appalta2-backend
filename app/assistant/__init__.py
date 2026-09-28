"""Módulo Asistente IA (antes AgriSense-Assistant).

Chat conversacional por estación: responde solo sobre los 6 sensores de clima
de la estación consultada, usando las mediciones de la base de datos.

Módulo autocontenido dentro del monolito: se integra con una sola línea en
app/main.py (`app.include_router(assistant_router, prefix="/api/v1")`) y no
modifica ninguna otra parte de la API.
"""

from app.assistant.api.router import router as assistant_router

__all__ = ["assistant_router"]
