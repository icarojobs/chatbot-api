"""upload sessions and parts for resumable document uploads

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "upload_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("total_size", sa.BigInteger(), nullable=False),
        sa.Column("part_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "upload_parts",
        sa.Column(
            "upload_id",
            sa.Uuid(),
            sa.ForeignKey("upload_sessions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("part_number", sa.Integer(), primary_key=True),
        sa.Column("data", sa.LargeBinary(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("upload_parts")
    op.drop_table("upload_sessions")
