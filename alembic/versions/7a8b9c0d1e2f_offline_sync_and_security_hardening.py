"""offline_sync_and_security_hardening

Revision ID: 7a8b9c0d1e2f
Revises: 5ce8dc2ce415
Create Date: 2026-10-21 12:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '7a8b9c0d1e2f'
down_revision: Union[str, Sequence[str], None] = '5ce8dc2ce415'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PUBLIC_TABLES = [
    'active_sessions',
    'attendance_events',
    'audit_logs',
    'doctors',
    'expenses',
    'face_embeddings',
    'franchises',
    'login_history',
    'otp_requests',
    'patient_status_histories',
    'patient_test_results',
    'patient_tests',
    'patients',
    'reports',
    'test_parameters',
    'test_price_history',
    'tests',
    'users',
    'cached_patient_registrations',
]


def upgrade() -> None:
    conn = op.get_bind()
    is_pg = conn.dialect.name == "postgresql"

    # 1. Create durable offline registration queue table
    op.create_table(
        'cached_patient_registrations',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('temp_ref_id', sa.String(length=64), nullable=False),
        sa.Column('idempotency_key', sa.String(length=255), nullable=False),
        sa.Column('owner_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('owner_role', sa.String(length=20), nullable=False),
        sa.Column('patient_data', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(length=20), server_default='PENDING', nullable=False),
        sa.Column('failure_reason', sa.Text(), nullable=True),
        sa.Column('error_details', sa.Text(), nullable=True),
        sa.Column('retry_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('last_attempt_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('synced_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('permanent_patient_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('permanent_patient_code', sa.String(length=32), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['permanent_patient_id'], ['patients.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_cached_patient_registrations_idempotency_key'), 'cached_patient_registrations', ['idempotency_key'], unique=True)
    op.create_index(op.f('ix_cached_patient_registrations_owner_id'), 'cached_patient_registrations', ['owner_id'], unique=False)
    op.create_index(op.f('ix_cached_patient_registrations_status'), 'cached_patient_registrations', ['status'], unique=False)
    op.create_index(op.f('ix_cached_patient_registrations_temp_ref_id'), 'cached_patient_registrations', ['temp_ref_id'], unique=True)

    # 2. Add foreign-key indexes for test_price_history
    op.create_index(op.f('ix_test_price_history_test_id'), 'test_price_history', ['test_id'], unique=False)
    op.create_index(op.f('ix_test_price_history_changed_by'), 'test_price_history', ['changed_by'], unique=False)

    # 3. Drop verified redundant duplicate indexes
    if is_pg:
        op.execute("DROP INDEX IF EXISTS idx_active_sessions_refresh_token_hash;")
        op.execute("DROP INDEX IF EXISTS idx_active_sessions_user_id;")
        op.execute("DROP INDEX IF EXISTS idx_face_embeddings_user_id;")
        op.execute("DROP INDEX IF EXISTS idx_login_history_user_id;")
        op.execute("DROP INDEX IF EXISTS idx_patient_test_results_patient_id;")
        op.execute("DROP INDEX IF EXISTS idx_patient_test_results_test_id;")
        op.execute("DROP INDEX IF EXISTS idx_patient_tests_patient_id;")
        op.execute("DROP INDEX IF EXISTS idx_patient_tests_test_id;")
        op.execute("DROP INDEX IF EXISTS idx_patients_collected_by;")
        op.execute("DROP INDEX IF EXISTS idx_patients_doctor_id;")
        op.execute("DROP INDEX IF EXISTS idx_reports_uploaded_by;")

        # 4. Enable Row Level Security (RLS) on public tables for defense-in-depth against unauthorized Data API access
        for tbl in PUBLIC_TABLES:
            op.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY;")


def downgrade() -> None:
    conn = op.get_bind()
    is_pg = conn.dialect.name == "postgresql"

    # Disable RLS
    if is_pg:
        for tbl in PUBLIC_TABLES:
            op.execute(f"ALTER TABLE {tbl} DISABLE ROW LEVEL SECURITY;")

        # Re-create dropped duplicate indexes
        op.execute("CREATE INDEX IF NOT EXISTS idx_active_sessions_refresh_token_hash ON active_sessions(refresh_token_hash);")
        op.execute("CREATE INDEX IF NOT EXISTS idx_active_sessions_user_id ON active_sessions(user_id);")
        op.execute("CREATE INDEX IF NOT EXISTS idx_face_embeddings_user_id ON face_embeddings(user_id);")
        op.execute("CREATE INDEX IF NOT EXISTS idx_login_history_user_id ON login_history(user_id);")
        op.execute("CREATE INDEX IF NOT EXISTS idx_patient_test_results_patient_id ON patient_test_results(patient_id);")
        op.execute("CREATE INDEX IF NOT EXISTS idx_patient_test_results_test_id ON patient_test_results(test_id);")
        op.execute("CREATE INDEX IF NOT EXISTS idx_patient_tests_patient_id ON patient_tests(patient_id);")
        op.execute("CREATE INDEX IF NOT EXISTS idx_patient_tests_test_id ON patient_tests(test_id);")
        op.execute("CREATE INDEX IF NOT EXISTS idx_patients_collected_by ON patients(collected_by);")
        op.execute("CREATE INDEX IF NOT EXISTS idx_patients_doctor_id ON patients(doctor_id);")
        op.execute("CREATE INDEX IF NOT EXISTS idx_reports_uploaded_by ON reports(uploaded_by);")

    # Drop test_price_history foreign key indexes
    op.drop_index(op.f('ix_test_price_history_changed_by'), table_name='test_price_history')
    op.drop_index(op.f('ix_test_price_history_test_id'), table_name='test_price_history')

    # Drop cached_patient_registrations
    op.drop_index(op.f('ix_cached_patient_registrations_temp_ref_id'), table_name='cached_patient_registrations')
    op.drop_index(op.f('ix_cached_patient_registrations_status'), table_name='cached_patient_registrations')
    op.drop_index(op.f('ix_cached_patient_registrations_owner_id'), table_name='cached_patient_registrations')
    op.drop_index(op.f('ix_cached_patient_registrations_idempotency_key'), table_name='cached_patient_registrations')
    op.drop_table('cached_patient_registrations')
