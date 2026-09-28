from sqlalchemy import Engine, create_engine

from app.assistant.config import AssistantSettings


def create_db_engine(settings: AssistantSettings, database_url: str | None = None) -> Engine:
    """Engine propio del asistente, con sesiones de SOLO LECTURA en PostgreSQL.

    Usa la misma DATABASE_URL del backend pero un pool separado: las consultas
    del chat no compiten con la API, y `default_transaction_read_only` impide
    cualquier escritura aunque hubiera un error de programación.
    """
    if database_url is None:
        from app.database.connection import DATABASE_URL as database_url

    return create_engine(
        database_url,
        pool_size=settings.assistant_db_pool_size,
        max_overflow=settings.assistant_db_max_overflow,
        pool_pre_ping=True,
        pool_recycle=1800,
        connect_args={
            "options": (
                "-c default_transaction_read_only=on "
                f"-c statement_timeout={settings.assistant_db_statement_timeout_ms}"
            ),
            "application_name": "appalta2-assistant",
        },
    )
