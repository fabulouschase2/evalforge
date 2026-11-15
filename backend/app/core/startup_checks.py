"""Production startup checks: migration state and configuration safety.

In production the application must never boot against a database whose
alembic revision is behind the latest migration — that would mean runtime
`create_all` drift or a half-migrated schema. Development and test keep the
convenient auto-create behavior (see app.main.lifespan).
"""
import logging

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger("evalforge.startup")


def get_head_revision() -> str:
    """The newest revision defined in alembic/versions."""
    alembic_cfg = Config("alembic.ini")
    script = ScriptDirectory.from_config(alembic_cfg)
    return script.get_current_head()


def get_stored_revision(engine: Engine) -> str | None:
    """The revision recorded in the database's alembic_version table (or None)."""
    insp = inspect(engine)
    if "alembic_version" not in insp.get_table_names():
        return None
    with engine.connect() as conn:
        row = conn.execute(text("SELECT version_num FROM alembic_version")).first()
    return row[0] if row else None


def check_migrations_up_to_date(engine: Engine) -> dict:
    """Raise RuntimeError when the stored revision is missing or behind head.

    Returns a status dict used by the readiness endpoint.
    """
    head = get_head_revision()
    stored = get_stored_revision(engine)
    status = {"head": head, "stored": stored, "up_to_date": stored == head}
    if stored is None:
        raise RuntimeError(
            "REFUSING TO START: the database has no alembic_version table. "
            "Run `alembic upgrade head` before starting the server in production."
        )
    if stored != head:
        raise RuntimeError(
            f"REFUSING TO START: database migration revision '{stored}' is not the "
            f"required head '{head}'. Run `alembic upgrade head`."
        )
    return status


def run_production_startup_checks(engine: Engine) -> dict:
    """All checks that must pass before serving production traffic."""
    migration = check_migrations_up_to_date(engine)
    logger.info("startup checks passed: migrations up to date (head=%s)", migration["head"])
    return {"migrations": migration}
