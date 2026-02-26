"""Add default fields to BookingParticipant

Revision ID: add_bp_default_fields
Revises: d8c58af30cc3
Create Date: 2026-02-09

"""
from alembic import op
import sqlalchemy as sa


revision = 'add_bp_default_fields'
down_revision = 'd8c58af30cc3'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('booking_participants')]
    
    with op.batch_alter_table('booking_participants', schema=None) as batch_op:
        if 'first_name' not in columns:
            batch_op.add_column(sa.Column('first_name', sa.String(64), nullable=True))
        if 'middle_name' not in columns:
            batch_op.add_column(sa.Column('middle_name', sa.String(64), nullable=True))
        if 'last_name' not in columns:
            batch_op.add_column(sa.Column('last_name', sa.String(64), nullable=True))
        if 'gender' not in columns:
            batch_op.add_column(sa.Column('gender', sa.String(32), nullable=True))
        if 'dob' not in columns:
            batch_op.add_column(sa.Column('dob', sa.Date(), nullable=True))
        if 'registration_type' not in columns:
            batch_op.add_column(sa.Column('registration_type', sa.String(32), nullable=True))
        if 'question_answers' not in columns:
            batch_op.add_column(sa.Column('question_answers', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('booking_participants', schema=None) as batch_op:
        batch_op.drop_column('question_answers')
        batch_op.drop_column('registration_type')
        batch_op.drop_column('dob')
        batch_op.drop_column('gender')
        batch_op.drop_column('last_name')
        batch_op.drop_column('middle_name')
        batch_op.drop_column('first_name')
