"""add oklahoma_withholding_tables (per-year OTC OW-2 tables)

Revision ID: b4e6f8a2c9d1
Revises: a7d3e9c1f5b2
Create Date: 2026-10-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b4e6f8a2c9d1'
down_revision: Union[str, None] = 'a7d3e9c1f5b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rows are not inserted here: app startup seeds an empty table from
    # models/oklahoma_withholding.py:DEFAULT_OKLAHOMA_TABLES (services/tax_years.py:seed_tax_years).
    op.create_table(
        'oklahoma_withholding_tables',
        sa.Column('year', sa.Integer(), autoincrement=False, nullable=False),
        sa.Column('data', sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint('year'),
    )


def downgrade() -> None:
    op.drop_table('oklahoma_withholding_tables')
