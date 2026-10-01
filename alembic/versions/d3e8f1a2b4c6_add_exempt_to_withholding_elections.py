"""add exempt to withholding elections

Revision ID: d3e8f1a2b4c6
Revises: b7f2a91c40d3
Create Date: 2026-09-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd3e8f1a2b4c6'
down_revision: Union[str, None] = 'b7f2a91c40d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default backfills existing elections as non-exempt.
    op.add_column('w4_elections', sa.Column('exempt', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('ok_withholding_elections', sa.Column('exempt', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column('ok_withholding_elections', 'exempt')
    op.drop_column('w4_elections', 'exempt')
