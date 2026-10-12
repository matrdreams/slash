"""Initial schema from the SQLModel metadata.

Revision ID: 0001
Revises:
Create Date: 2026-10-12
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlmodel import SQLModel

    import slash.store.tables  # noqa: F401

    SQLModel.metadata.create_all(op.get_bind())


def downgrade() -> None:
    from sqlmodel import SQLModel

    import slash.store.tables  # noqa: F401

    SQLModel.metadata.drop_all(op.get_bind())
