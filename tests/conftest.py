from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app import (
    db,
    models,  # noqa: F401 — регистрирует таблицы в Base.metadata
)


@pytest.fixture
def test_database(tmp_path, monkeypatch) -> Iterator[sessionmaker[Session]]:
    database_path = tmp_path / "test.db"
    test_engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    test_session_factory = sessionmaker(
        bind=test_engine,
        autoflush=False,
        expire_on_commit=False,
    )
    monkeypatch.setattr(db, "engine", test_engine)
    monkeypatch.setattr(db, "SessionLocal", test_session_factory)
    db.Base.metadata.create_all(bind=test_engine)

    yield test_session_factory

    test_engine.dispose()
