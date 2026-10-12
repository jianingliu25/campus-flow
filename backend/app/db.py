"""Private SQLite database with actual Alembic migrations, foreign keys and WAL."""

from contextlib import contextmanager
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.config import ROOT
from app.models import Workspace


class Database:
    def __init__(self, directory: Path):
        directory = directory.expanduser().resolve()
        if directory.is_relative_to(ROOT):
            raise ValueError("Runtime data must stay outside the source repository")
        directory.mkdir(parents=True, exist_ok=True)
        if os.name != 'nt':
            directory.chmod(0o700)
        self.path = directory / "campus-flow.db"
        self.engine = create_engine(f"sqlite:///{self.path.as_posix()}", connect_args={"check_same_thread": False, "timeout": 10}, hide_parameters=True)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

        @event.listens_for(self.engine, "connect")
        def configure_sqlite(connection, record):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=10000")
            cursor.close()

    def migration_config(self, connection=None):
        config = Config(str(ROOT / "backend/alembic.ini"))
        config.set_main_option("script_location", str(ROOT / "backend/migrations"))
        if connection is not None:
            config.attributes["connection"] = connection
        return config

    def migrate(self):
        with self.engine.begin() as connection:
            command.upgrade(self.migration_config(connection), "head")

    @contextmanager
    def transaction(self):
        with self.sessions.begin() as session:
            yield session

    def ensure_workspace(self, timezone):
        with self.transaction() as session:
            workspace = session.scalar(select(Workspace).order_by(Workspace.created_at).limit(1))
            if workspace is None:
                workspace = Workspace(timezone=timezone)
                session.add(workspace)
                session.flush()
            return workspace.id

    def close(self):
        self.engine.dispose()
