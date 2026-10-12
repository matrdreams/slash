import sqlite3

from alembic import command
from alembic.config import Config


def test_alembic_upgrade_creates_tables(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'migrated.db'}"
    monkeypatch.setenv("SLASH_DB_URL", url)
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    connection = sqlite3.connect(tmp_path / "migrated.db")
    names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"device", "task", "step", "snapshot", "takeover", "user"} <= names
