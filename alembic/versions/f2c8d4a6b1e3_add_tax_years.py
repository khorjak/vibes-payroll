"""add tax_years (per-year wage bases)

Revision ID: f2c8d4a6b1e3
Revises: e5a1c7b9d2f4
Create Date: 2026-10-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f2c8d4a6b1e3'
down_revision: Union[str, None] = 'e5a1c7b9d2f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rows are not inserted here: app startup seeds an empty table from
    # models/tax_year.py:DEFAULT_TAX_YEARS (services/tax_years.py:seed_tax_years).
    op.create_table(
        'tax_years',
        sa.Column('year', sa.Integer(), autoincrement=False, nullable=False),
        sa.Column('ss_wage_base', sa.Numeric(12, 2), nullable=False),
        sa.Column('ok_suta_wage_base', sa.Numeric(12, 2), nullable=False),
        sa.PrimaryKeyConstraint('year'),
    )


def downgrade() -> None:
    op.drop_table('tax_years')
