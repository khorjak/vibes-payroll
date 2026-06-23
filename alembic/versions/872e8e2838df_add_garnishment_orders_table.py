"""add garnishment_orders table

Revision ID: 872e8e2838df
Revises: 7bc3e26e0a82
Create Date: 2026-06-22 23:27:12.602361

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '872e8e2838df'
down_revision: Union[str, None] = '7bc3e26e0a82'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'garnishment_orders',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('employee_id', sa.Integer(), sa.ForeignKey('employees.id'), nullable=False),
        sa.Column('garnishment_type', sa.String(30), nullable=False),
        sa.Column('case_number', sa.String(100), nullable=True),
        sa.Column('payee_name', sa.String(200), nullable=False),
        sa.Column('amount', sa.Numeric(12, 2), server_default='0'),
        sa.Column('percent', sa.Numeric(6, 4), nullable=True),
        sa.Column('amount_type', sa.String(10), server_default='fixed'),
        sa.Column('max_total', sa.Numeric(12, 2), nullable=True),
        sa.Column('ytd_withheld', sa.Numeric(12, 2), server_default='0'),
        sa.Column('effective_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=True),
        sa.Column('active', sa.Boolean(), server_default='1'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('garnishment_orders')
