from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from app import models  # noqa: F401 — регистрирует таблицы в metadata
from app.config import settings
from app.db import Base


def test_initial_migration_upgrade_and_downgrade(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "migration.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setattr(settings, "database_url", database_url)
    alembic_config = Config("alembic.ini")

    command.upgrade(alembic_config, "head")

    engine = create_engine(database_url)
    inspector = inspect(engine)
    assert set(inspector.get_table_names()) == {
        "alembic_version",
        "payments",
        "tariffs",
    }
    assert inspector.get_foreign_keys("payments")[0]["referred_table"] == "tariffs"
    assert inspector.get_unique_constraints("payments") == [
        {
            "name": "uq_payments_idempotency_key",
            "column_names": ["idempotency_key"],
        }
    ]
    with engine.connect() as connection:
        migration_context = MigrationContext.configure(connection)
        assert compare_metadata(migration_context, Base.metadata) == []

    command.downgrade(alembic_config, "base")
    assert inspect(engine).get_table_names() == ["alembic_version"]
    engine.dispose()
