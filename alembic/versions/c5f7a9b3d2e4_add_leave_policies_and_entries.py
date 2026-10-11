"""add leave_policies and leave_entries (PTO / sick accrual balances)

Revision ID: c5f7a9b3d2e4
Revises: b4e6f8a2c9d1
Create Date: 2026-10-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c5f7a9b3d2e4'
down_revision: Union[str, None] = 'b4e6f8a2c9d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'leave_policies',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('employee_id', sa.Integer(), nullable=False),
        sa.Column('leave_type', sa.String(length=10), nullable=False),
        sa.Column('method', sa.String(length=20), nullable=False),
        sa.Column('rate', sa.Numeric(precision=8, scale=4), nullable=False),
        sa.Column('max_balance', sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column('carryover_limit', sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column('carryover_since', sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('employee_id', 'leave_type'),
    )
    op.create_index(op.f('ix_leave_policies_employee_id'), 'leave_policies', ['employee_id'], unique=False)
    op.create_table(
        'leave_entries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('employee_id', sa.Integer(), nullable=False),
        sa.Column('leave_type', sa.String(length=10), nullable=False),
        sa.Column('entry_date', sa.Date(), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('hours', sa.Numeric(precision=8, scale=2), nullable=False),
        sa.Column('paycheck_id', sa.Integer(), nullable=True),
        sa.Column('note', sa.String(length=200), nullable=True),
        sa.Column('created_by', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id']),
        sa.ForeignKeyConstraint(['paycheck_id'], ['paychecks.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_leave_entries_employee_id'), 'leave_entries', ['employee_id'], unique=False)
    op.create_index(op.f('ix_leave_entries_paycheck_id'), 'leave_entries', ['paycheck_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_leave_entries_paycheck_id'), table_name='leave_entries')
    op.drop_index(op.f('ix_leave_entries_employee_id'), table_name='leave_entries')
    op.drop_table('leave_entries')
    op.drop_index(op.f('ix_leave_policies_employee_id'), table_name='leave_policies')
    op.drop_table('leave_policies')
