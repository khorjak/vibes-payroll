"""add federal_withholding_tables (per-year Pub. 15-T tables)

Revision ID: a7d3e9c1f5b2
Revises: f2c8d4a6b1e3
Create Date: 2026-10-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a7d3e9c1f5b2'
down_revision: Union[str, None] = 'f2c8d4a6b1e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rows are not inserted here: app startup seeds an empty table from
    # models/federal_withholding.py:DEFAULT_FEDERAL_TABLES (services/tax_years.py:seed_tax_years).
    op.create_table(
        'federal_withholding_tables',
        sa.Column('year', sa.Integer(), autoincrement=False, nullable=False),
        sa.Column('data', sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint('year'),
    )


def downgrade() -> None:
    op.drop_table('federal_withholding_tables')
