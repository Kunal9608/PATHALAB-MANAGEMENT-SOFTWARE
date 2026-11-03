"""Initial migration

Revision ID: 6742aa9f0232
Revises: 
Create Date: 2026-07-20 10:34:24.547340

"""
from typing import Sequence, Union
import os

from alembic import op
import sqlalchemy as sa
from backend.app.config import settings


# revision identifiers, used by Alembic.
revision: str = '6742aa9f0232'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    is_pg = conn.dialect.name == "postgresql"
    inspector = sa.inspect(conn)
    existing_tables = set(inspector.get_table_names())

    if is_pg:
        try:
            op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")
            op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";')
            op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
        except Exception:
            pass

    # If this is a fresh database (e.g. clean staging, local, test, or new production deployment),
    # ensure all base application tables are created.
    if 'users' not in existing_tables:
        from backend.app.core.db import Base
        import backend.app.models  # noqa: F401
        
        # Subsequent migrations create cached_patient_registrations (7a8b9c0d1e2f) and admin_vault_items (9c0d1e2f3a4b)
        subsequent_tables = {'cached_patient_registrations', 'admin_vault_items'}
        initial_tables = [
            tbl for name, tbl in Base.metadata.tables.items()
            if name not in subsequent_tables
        ]
        Base.metadata.create_all(bind=conn, tables=initial_tables, checkfirst=True)

    # Safe idempotent index and column alignments
    op.drop_index(op.f('idx_active_sessions_refresh_token_hash'), table_name='active_sessions', if_exists=True)
    op.drop_index(op.f('idx_active_sessions_user_id'), table_name='active_sessions', if_exists=True)
    op.create_index(op.f('ix_active_sessions_refresh_token_hash'), 'active_sessions', ['refresh_token_hash'], unique=False, if_not_exists=True)
    op.create_index(op.f('ix_active_sessions_user_id'), 'active_sessions', ['user_id'], unique=False, if_not_exists=True)
    op.drop_index(op.f('idx_attendance_user_time'), table_name='attendance_events', if_exists=True)
    op.drop_index(op.f('idx_audit_logs_action_time'), table_name='audit_logs', if_exists=True)
    op.drop_index(op.f('idx_audit_logs_actor_time'), table_name='audit_logs', if_exists=True)

    if is_pg:
        try:
            op.alter_column('doctors', 'commission_pct',
                       existing_type=sa.NUMERIC(precision=5, scale=2),
                       nullable=False,
                       existing_server_default=sa.text('0.0'))
        except Exception:
            pass

    op.drop_index(op.f('idx_expenses_date_cat'), table_name='expenses', if_exists=True)
    op.drop_index(op.f('idx_expenses_expense_date'), table_name='expenses', if_exists=True)
    op.create_index(op.f('ix_expenses_expense_date'), 'expenses', ['expense_date'], unique=False, if_not_exists=True)
    op.create_index(op.f('ix_expenses_recorded_by'), 'expenses', ['recorded_by'], unique=False, if_not_exists=True)

    disable_pgvector = getattr(settings, "DISABLE_PGVECTOR", False) or os.getenv("DISABLE_PGVECTOR", "false").lower() == "true"
    if is_pg and not disable_pgvector:
        try:
            ext_check = conn.execute(sa.text("SELECT 1 FROM pg_extension WHERE extname = 'vector';")).fetchone()
            if not ext_check:
                conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector;"))
            import pgvector.sqlalchemy
            op.alter_column('face_embeddings', 'embedding',
                       existing_type=sa.TEXT(),
                       type_=pgvector.sqlalchemy.vector.VECTOR(dim=128),
                       existing_nullable=False)
        except Exception:
            pass

    op.drop_index(op.f('idx_face_embeddings_user_id'), table_name='face_embeddings', if_exists=True)
    op.create_index(op.f('ix_face_embeddings_user_id'), 'face_embeddings', ['user_id'], unique=False, if_not_exists=True)
    op.drop_index(op.f('idx_login_history_email_attempted'), table_name='login_history', if_exists=True)
    op.drop_index(op.f('idx_login_history_email_time'), table_name='login_history', if_exists=True)
    op.drop_index(op.f('idx_login_history_user_id'), table_name='login_history', if_exists=True)
    op.create_index(op.f('ix_login_history_email_attempted'), 'login_history', ['email_attempted'], unique=False, if_not_exists=True)
    op.create_index(op.f('ix_login_history_user_id'), 'login_history', ['user_id'], unique=False, if_not_exists=True)
    op.drop_index(op.f('idx_patient_test_results_patient_id'), table_name='patient_test_results', if_exists=True)
    op.drop_index(op.f('idx_patient_test_results_test_id'), table_name='patient_test_results', if_exists=True)
    op.drop_index(op.f('idx_patient_tests_patient_id'), table_name='patient_tests', if_exists=True)
    op.drop_index(op.f('idx_patient_tests_test_id'), table_name='patient_tests', if_exists=True)
    op.create_index(op.f('ix_patient_tests_patient_id'), 'patient_tests', ['patient_id'], unique=False, if_not_exists=True)
    op.create_index(op.f('ix_patient_tests_test_id'), 'patient_tests', ['test_id'], unique=False, if_not_exists=True)

    if is_pg:
        op.drop_index(op.f('idx_patient_code_prefix'), table_name='patients', postgresql_ops={'patient_code': 'varchar_pattern_ops'}, postgresql_where='(deleted_at IS NULL)', if_exists=True)
        op.drop_index(op.f('idx_patients_active_collector'), table_name='patients', postgresql_where='(deleted_at IS NULL)', if_exists=True)
        op.drop_index(op.f('idx_patients_active_created'), table_name='patients', postgresql_where='(deleted_at IS NULL)', if_exists=True)
        op.drop_index(op.f('idx_patients_active_doctor'), table_name='patients', postgresql_where='(deleted_at IS NULL)', if_exists=True)
        op.drop_index(op.f('idx_patients_active_mobile'), table_name='patients', postgresql_where='(deleted_at IS NULL)', if_exists=True)
        op.drop_index(op.f('idx_patients_active_status'), table_name='patients', postgresql_where='(deleted_at IS NULL)', if_exists=True)
        op.drop_index(op.f('idx_patients_amount_due'), table_name='patients', postgresql_where='((deleted_at IS NULL) AND (amount_paid < (total_amount - discount_amount)))', if_exists=True)
        op.drop_index(op.f('idx_patients_collected_by'), table_name='patients', if_exists=True)
        op.drop_index(op.f('idx_patients_doctor_id'), table_name='patients', if_exists=True)
        op.drop_index(op.f('idx_patients_mobile_prefix'), table_name='patients', postgresql_ops={'mobile': 'varchar_pattern_ops'}, postgresql_where='(deleted_at IS NULL)', if_exists=True)
        op.drop_index(op.f('idx_patients_name_trgm'), table_name='patients', postgresql_ops={'name': 'gin_trgm_ops'}, postgresql_using='gin', if_exists=True)
        op.drop_index(op.f('idx_patients_payment_split'), table_name='patients', postgresql_where='(deleted_at IS NULL)', if_exists=True)

    op.create_index(op.f('ix_patients_collected_by'), 'patients', ['collected_by'], unique=False, if_not_exists=True)
    op.create_index(op.f('ix_patients_doctor_id'), 'patients', ['doctor_id'], unique=False, if_not_exists=True)
    op.drop_index(op.f('idx_reports_patient_id'), table_name='reports', if_exists=True)
    op.drop_index(op.f('idx_reports_patient_version'), table_name='reports', if_exists=True)
    op.drop_index(op.f('idx_reports_uploaded_by'), table_name='reports', if_exists=True)
    op.drop_index(op.f('idx_reports_verification_hash'), table_name='reports', if_exists=True)
    op.create_index(op.f('ix_reports_patient_id'), 'reports', ['patient_id'], unique=False, if_not_exists=True)
    op.create_index(op.f('ix_reports_uploaded_by'), 'reports', ['uploaded_by'], unique=False, if_not_exists=True)
    op.drop_index(op.f('idx_test_parameters_test_id'), table_name='test_parameters', if_exists=True)
    op.drop_index(op.f('idx_tests_name_lower'), table_name='tests', if_exists=True)

    if is_pg:
        op.drop_index(op.f('idx_tests_name_trgm'), table_name='tests', postgresql_ops={'name': 'gin_trgm_ops'}, postgresql_using='gin', if_exists=True)
        op.drop_index(op.f('idx_users_staff_active'), table_name='users', postgresql_where="(role = 'staff'::role_enum)", if_exists=True)


def downgrade() -> None:
    """Downgrade schema."""
    conn = op.get_bind()
    is_pg = conn.dialect.name == "postgresql"

    if is_pg:
        op.create_index(op.f('idx_users_staff_active'), 'users', [sa.literal_column('created_at DESC')], unique=False, postgresql_where="(role = 'staff'::role_enum)", if_not_exists=True)
        op.create_index(op.f('idx_tests_name_trgm'), 'tests', ['name'], unique=False, postgresql_ops={'name': 'gin_trgm_ops'}, postgresql_using='gin', if_not_exists=True)
        op.create_index(op.f('idx_tests_name_lower'), 'tests', [sa.literal_column('lower(name::text)')], unique=False, if_not_exists=True)
        op.create_index(op.f('idx_test_parameters_test_id'), 'test_parameters', ['test_id', 'display_order'], unique=False, if_not_exists=True)

    op.drop_index(op.f('ix_reports_uploaded_by'), table_name='reports', if_exists=True)
    op.drop_index(op.f('ix_reports_patient_id'), table_name='reports', if_exists=True)

    if is_pg:
        op.create_index(op.f('idx_reports_verification_hash'), 'reports', ['verification_hash'], unique=False, if_not_exists=True)
        op.create_index(op.f('idx_reports_uploaded_by'), 'reports', ['uploaded_by'], unique=False, if_not_exists=True)
        op.create_index(op.f('idx_reports_patient_version'), 'reports', ['patient_id', sa.literal_column('version DESC')], unique=False, if_not_exists=True)
        op.create_index(op.f('idx_reports_patient_id'), 'reports', ['patient_id'], unique=False, if_not_exists=True)

    op.drop_index(op.f('ix_patients_doctor_id'), table_name='patients', if_exists=True)
    op.drop_index(op.f('ix_patients_collected_by'), table_name='patients', if_exists=True)

    if is_pg:
        op.create_index(op.f('idx_patients_payment_split'), 'patients', ['payment_mode', sa.literal_column('created_at DESC')], unique=False, postgresql_where='(deleted_at IS NULL)', if_not_exists=True)
        op.create_index(op.f('idx_patients_name_trgm'), 'patients', ['name'], unique=False, postgresql_ops={'name': 'gin_trgm_ops'}, postgresql_using='gin', if_not_exists=True)
        op.create_index(op.f('idx_patients_mobile_prefix'), 'patients', ['mobile'], unique=False, postgresql_ops={'mobile': 'varchar_pattern_ops'}, postgresql_where='(deleted_at IS NULL)', if_not_exists=True)
        op.create_index(op.f('idx_patients_doctor_id'), 'patients', ['doctor_id'], unique=False, if_not_exists=True)
        op.create_index(op.f('idx_patients_collected_by'), 'patients', ['collected_by'], unique=False, if_not_exists=True)
        op.create_index(op.f('idx_patients_amount_due'), 'patients', [sa.literal_column('created_at DESC')], unique=False, postgresql_where='((deleted_at IS NULL) AND (amount_paid < (total_amount - discount_amount)))', if_not_exists=True)
        op.create_index(op.f('idx_patients_active_status'), 'patients', ['status', sa.literal_column('created_at DESC')], unique=False, postgresql_where='(deleted_at IS NULL)', if_not_exists=True)
        op.create_index(op.f('idx_patients_active_mobile'), 'patients', ['mobile'], unique=False, postgresql_where='(deleted_at IS NULL)', if_not_exists=True)
        op.create_index(op.f('idx_patients_active_doctor'), 'patients', ['doctor_id', sa.literal_column('created_at DESC')], unique=False, postgresql_where='(deleted_at IS NULL)', if_not_exists=True)
        op.create_index(op.f('idx_patients_active_created'), 'patients', [sa.literal_column('created_at DESC')], unique=False, postgresql_where='(deleted_at IS NULL)', if_not_exists=True)
        op.create_index(op.f('idx_patients_active_collector'), 'patients', ['collected_by', sa.literal_column('created_at DESC')], unique=False, postgresql_where='(deleted_at IS NULL)', if_not_exists=True)
        op.create_index(op.f('idx_patient_code_prefix'), 'patients', ['patient_code'], unique=False, postgresql_ops={'patient_code': 'varchar_pattern_ops'}, postgresql_where='(deleted_at IS NULL)', if_not_exists=True)

    op.drop_index(op.f('ix_patient_tests_test_id'), table_name='patient_tests', if_exists=True)
    op.drop_index(op.f('ix_patient_tests_patient_id'), table_name='patient_tests', if_exists=True)

    if is_pg:
        op.create_index(op.f('idx_patient_tests_test_id'), 'patient_tests', ['test_id'], unique=False, if_not_exists=True)
        op.create_index(op.f('idx_patient_tests_patient_id'), 'patient_tests', ['patient_id'], unique=False, if_not_exists=True)
        op.create_index(op.f('idx_patient_test_results_test_id'), 'patient_test_results', ['test_id'], unique=False, if_not_exists=True)
        op.create_index(op.f('idx_patient_test_results_patient_id'), 'patient_test_results', ['patient_id'], unique=False, if_not_exists=True)

    op.drop_index(op.f('ix_login_history_user_id'), table_name='login_history', if_exists=True)
    op.drop_index(op.f('ix_login_history_email_attempted'), table_name='login_history', if_exists=True)

    if is_pg:
        op.create_index(op.f('idx_login_history_user_id'), 'login_history', ['user_id'], unique=False, if_not_exists=True)
        op.create_index(op.f('idx_login_history_email_time'), 'login_history', ['email_attempted', sa.literal_column('attempted_at DESC')], unique=False, if_not_exists=True)
        op.create_index(op.f('idx_login_history_email_attempted'), 'login_history', ['email_attempted'], unique=False, if_not_exists=True)

    op.drop_index(op.f('ix_face_embeddings_user_id'), table_name='face_embeddings', if_exists=True)

    if is_pg:
        op.create_index(op.f('idx_face_embeddings_user_id'), 'face_embeddings', ['user_id'], unique=False, if_not_exists=True)
        disable_pgvector = getattr(settings, "DISABLE_PGVECTOR", False) or os.getenv("DISABLE_PGVECTOR", "false").lower() == "true"
        if not disable_pgvector:
            try:
                import pgvector.sqlalchemy
                op.alter_column('face_embeddings', 'embedding',
                           existing_type=pgvector.sqlalchemy.vector.VECTOR(dim=128),
                           type_=sa.TEXT(),
                           existing_nullable=False)
            except Exception:
                pass

    op.drop_index(op.f('ix_expenses_recorded_by'), table_name='expenses', if_exists=True)
    op.drop_index(op.f('ix_expenses_expense_date'), table_name='expenses', if_exists=True)

    if is_pg:
        op.create_index(op.f('idx_expenses_expense_date'), 'expenses', ['expense_date'], unique=False, if_not_exists=True)
        op.create_index(op.f('idx_expenses_date_cat'), 'expenses', [sa.literal_column('expense_date DESC'), 'category'], unique=False, if_not_exists=True)
        try:
            op.alter_column('doctors', 'commission_pct',
                       existing_type=sa.NUMERIC(precision=5, scale=2),
                       nullable=True,
                       existing_server_default=sa.text('0.0'))
        except Exception:
            pass
        op.create_index(op.f('idx_audit_logs_actor_time'), 'audit_logs', ['actor_user_id', sa.literal_column('occurred_at DESC')], unique=False, if_not_exists=True)
        op.create_index(op.f('idx_audit_logs_action_time'), 'audit_logs', ['action', sa.literal_column('occurred_at DESC')], unique=False, if_not_exists=True)
        op.create_index(op.f('idx_attendance_user_time'), 'attendance_events', ['user_id', sa.literal_column('event_time DESC')], unique=False, if_not_exists=True)

    op.drop_index(op.f('ix_active_sessions_user_id'), table_name='active_sessions', if_exists=True)
    op.drop_index(op.f('ix_active_sessions_refresh_token_hash'), table_name='active_sessions', if_exists=True)

    if is_pg:
        op.create_index(op.f('idx_active_sessions_user_id'), 'active_sessions', ['user_id'], unique=False, if_not_exists=True)
        op.create_index(op.f('idx_active_sessions_refresh_token_hash'), 'active_sessions', ['refresh_token_hash'], unique=False, if_not_exists=True)
