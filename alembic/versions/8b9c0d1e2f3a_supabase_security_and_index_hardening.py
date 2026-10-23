"""supabase_security_and_index_hardening

Revision ID: 8b9c0d1e2f3a
Revises: 7a8b9c0d1e2f
Create Date: 2026-10-22 14:20:00.000000

Reconciles Supabase security and performance findings:
1. Adds covering indexes for unindexed foreign keys:
   - attendance_events.user_id
   - audit_logs.actor_user_id
   - cached_patient_registrations.permanent_patient_id
2. Enables Row Level Security (RLS) on public.alembic_version.
3. Creates explicit defensive policies on all public tables to eliminate Supabase Security Advisor
   warnings ("RLS enabled but no policies exist") while maintaining backend service_role / postgres access.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8b9c0d1e2f3a'
down_revision: Union[str, Sequence[str], None] = '7a8b9c0d1e2f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ALL_TABLES = [
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
    'alembic_version',
]


def upgrade() -> None:
    conn = op.get_bind()
    is_pg = conn.dialect.name == "postgresql"

    # 1. Add missing covering indexes for foreign keys
    op.create_index(
        'ix_attendance_events_user_id',
        'attendance_events',
        ['user_id'],
        unique=False,
        if_not_exists=True
    )
    op.create_index(
        'ix_audit_logs_actor_user_id',
        'audit_logs',
        ['actor_user_id'],
        unique=False,
        if_not_exists=True
    )
    op.create_index(
        'ix_cached_patient_registrations_permanent_patient_id',
        'cached_patient_registrations',
        ['permanent_patient_id'],
        unique=False,
        if_not_exists=True
    )

    if is_pg:
        # 2. Enable RLS on alembic_version
        op.execute("ALTER TABLE alembic_version ENABLE ROW LEVEL SECURITY;")

        # 3. Add explicit defensive RLS policies for each table
        for tbl in ALL_TABLES:
            policy_name = f"service_and_backend_all_{tbl}"
            op.execute(f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_policies 
                        WHERE schemaname = 'public' 
                          AND tablename = '{tbl}' 
                          AND policyname = '{policy_name}'
                    ) THEN
                        CREATE POLICY "{policy_name}" ON public.{tbl}
                            FOR ALL 
                            TO postgres, service_role 
                            USING (true) 
                            WITH CHECK (true);
                    END IF;
                END $$;
            """)


def downgrade() -> None:
    conn = op.get_bind()
    is_pg = conn.dialect.name == "postgresql"

    if is_pg:
        # Drop defensive policies
        for tbl in ALL_TABLES:
            policy_name = f"service_and_backend_all_{tbl}"
            op.execute(f'DROP POLICY IF EXISTS "{policy_name}" ON public.{tbl};')

        # Disable RLS on alembic_version
        op.execute("ALTER TABLE alembic_version DISABLE ROW LEVEL SECURITY;")

    # Drop indexes
    op.drop_index('ix_cached_patient_registrations_permanent_patient_id', table_name='cached_patient_registrations')
    op.drop_index('ix_audit_logs_actor_user_id', table_name='audit_logs')
    op.drop_index('ix_attendance_events_user_id', table_name='attendance_events')
