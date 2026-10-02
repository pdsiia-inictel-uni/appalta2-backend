from sqlalchemy import Engine, create_engine, make_url

from app.assistant.config import AssistantSettings


def create_db_engine(settings: AssistantSettings, database_url: str | None = None) -> Engine:
    """Engine propio del asistente, con sesiones de SOLO LECTURA en PostgreSQL.

    Usa la misma DATABASE_URL del backend pero un pool separado: las consultas
    del chat no compiten con la API, y `default_transaction_read_only` impide
    cualquier escritura aunque hubiera un error de programación.
    """
    if database_url is None:
        from app.database.connection import DATABASE_URL as database_url

    session_params = {
        "default_transaction_read_only": "on",
        "statement_timeout": str(settings.assistant_db_statement_timeout_ms),
    }
    if make_url(database_url).get_driver_name() == "pg8000":
        # pg8000 (Python puro) no entiende "options" de libpq; envía los parámetros al iniciar la sesión.
        connect_args = {"startup_params": session_params}
    else:
        connect_args = {"options": " ".join(f"-c {k}={v}" for k, v in session_params.items())}

    return create_engine(
        database_url,
        pool_size=settings.assistant_db_pool_size,
        max_overflow=settings.assistant_db_max_overflow,
        pool_pre_ping=True,
        pool_recycle=1800,
        connect_args={**connect_args, "application_name": "appalta2-assistant"},
    )
