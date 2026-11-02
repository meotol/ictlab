"""Add professional engineer summaries and assets.

Revision ID: 20261102_01
Revises: None (repository baseline is managed externally)
"""
from alembic import op
import sqlalchemy as sa

revision = "20261102_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("pe_summaries", sa.Column("id", sa.BigInteger(), primary_key=True), sa.Column("title", sa.String(500), nullable=False), sa.Column("field", sa.String(100), nullable=False), sa.Column("keywords", sa.String(1000), nullable=False, server_default=""), sa.Column("description", sa.Text(), nullable=False, server_default=""), sa.Column("is_published", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index("ix_pe_summaries_field", "pe_summaries", ["field"])
    op.create_index("ix_pe_summaries_is_published", "pe_summaries", ["is_published"])
    op.create_table("pe_summary_assets", sa.Column("id", sa.BigInteger(), primary_key=True), sa.Column("summary_id", sa.BigInteger(), sa.ForeignKey("pe_summaries.id", ondelete="CASCADE"), nullable=False), sa.Column("kind", sa.String(20), nullable=False), sa.Column("original_name", sa.String(255), nullable=False), sa.Column("stored_name", sa.String(80), nullable=False, unique=True), sa.Column("mime_type", sa.String(100), nullable=False), sa.Column("size_bytes", sa.BigInteger(), nullable=False), sa.Column("sha256", sa.String(64), nullable=False), sa.Column("preview_name", sa.String(80)), sa.Column("conversion_status", sa.String(30), nullable=False), sa.Column("preview_verified", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("lyrics", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index("ix_pe_summary_assets_summary_id", "pe_summary_assets", ["summary_id"])


def downgrade():
    op.drop_table("pe_summary_assets")
    op.drop_table("pe_summaries")
