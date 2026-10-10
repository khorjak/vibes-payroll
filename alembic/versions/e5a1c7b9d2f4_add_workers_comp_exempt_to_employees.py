"""add workers_comp_exempt to employees

Revision ID: e5a1c7b9d2f4
Revises: d3e8f1a2b4c6
Create Date: 2026-10-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e5a1c7b9d2f4'
down_revision: Union[str, None] = 'd3e8f1a2b4c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default backfills every existing employee as not exempt.
    with op.batch_alter_table('employees') as batch:
        batch.add_column(sa.Column('workers_comp_exempt', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table('employees') as batch:
        batch.drop_column('workers_comp_exempt')
