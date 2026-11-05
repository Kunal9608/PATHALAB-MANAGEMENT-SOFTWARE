"""enterprise_database_hardening_and_indexes

Revision ID: a2b3c4d5e6f7
Revises: 9c0d1e2f3a4b
Create Date: 2026-11-05 18:45:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

# revision identifiers, used by Alembic.
revision = 'a2b3c4d5e6f7'
down_revision = '9c0d1e2f3a4b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    is_postgres = conn.dialect.name == "postgresql"

    # -------------------------------------------------------------------------
    # 1. DB-04: Database-level CHECK Constraints for Financial and Patient Integrity
    # -------------------------------------------------------------------------
    # Patients table checks
    op.create_check_constraint(
        "chk_patients_positive_amounts",
        "patients",
        "(total_amount >= 0) AND (discount_amount IS NULL OR discount_amount >= 0) AND (amount_paid IS NULL OR amount_paid >= 0)"
    )
    op.create_check_constraint(
        "chk_patients_discount_le_total",
        "patients",
        "discount_amount IS NULL OR discount_amount <= total_amount"
    )
    op.create_check_constraint(
        "chk_patients_commission_range",
        "patients",
        "referred_doctor_commission_pct IS NULL OR (referred_doctor_commission_pct >= 0 AND referred_doctor_commission_pct <= 100)"
    )

    # Expenses table checks
    op.create_check_constraint(
        "chk_expenses_positive_amount",
        "expenses",
        "amount > 0"
    )

    # -------------------------------------------------------------------------
    # 2. DB-05: Advanced Composite, Partial & Covering Indexes
    # -------------------------------------------------------------------------
    # Partial index for active unrevoked sessions (instant lookup on shared terminals)
    op.create_index(
        "idx_active_sessions_unrevoked",
        "active_sessions",
        ["user_id", "issued_at"],
        postgresql_where=sa.text("revoked_at IS NULL") if is_postgres else None,
        if_not_exists=True
    )

    # Partial composite index for lab patient status progression (sample_collected, under_process, report_ready)
    op.create_index(
        "idx_patients_status_created",
        "patients",
        ["status", "created_at"],
        postgresql_where=sa.text("deleted_at IS NULL") if is_postgres else None,
        if_not_exists=True
    )

    # Composite index for diagnostic reports sorted by upload date
    op.create_index(
        "idx_reports_patient_uploaded",
        "reports",
        ["patient_id", "uploaded_at"],
        if_not_exists=True
    )

    # Composite index for finance expense filtering by category and date
    op.create_index(
        "idx_expenses_category_date",
        "expenses",
        ["category", "expense_date"],
        if_not_exists=True
    )

    # Composite index for AI Copilot conversation history per user
    op.create_index(
        "idx_copilot_messages_user_created",
        "copilot_messages",
        ["user_id", "created_at"],
        if_not_exists=True
    )

    # -------------------------------------------------------------------------
    # 3. DB-06: Uniform Row-Level Security (RLS) for copilot_messages
    # -------------------------------------------------------------------------
    if is_postgres:
        op.execute("ALTER TABLE copilot_messages ENABLE ROW LEVEL SECURITY;")
        op.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_policies 
                    WHERE schemaname = 'public' 
                      AND tablename = 'copilot_messages' 
                      AND policyname = 'service_and_backend_all_copilot_messages'
                ) THEN
                    CREATE POLICY service_and_backend_all_copilot_messages
                        ON copilot_messages
                        FOR ALL
                        TO PUBLIC
                        USING (true)
                        WITH CHECK (true);
                END IF;
            END $$;
        """)


def downgrade() -> None:
    conn = op.get_bind()
    is_postgres = conn.dialect.name == "postgresql"

    # DB-06: RLS removal for copilot_messages
    if is_postgres:
        op.execute("DROP POLICY IF EXISTS service_and_backend_all_copilot_messages ON copilot_messages;")
        op.execute("ALTER TABLE copilot_messages DISABLE ROW LEVEL SECURITY;")

    # DB-05: Drop indexes
    op.drop_index("idx_copilot_messages_user_created", table_name="copilot_messages", if_exists=True)
    op.drop_index("idx_expenses_category_date", table_name="expenses", if_exists=True)
    op.drop_index("idx_reports_patient_uploaded", table_name="reports", if_exists=True)
    op.drop_index("idx_patients_status_created", table_name="patients", if_exists=True)
    op.drop_index("idx_active_sessions_unrevoked", table_name="active_sessions", if_exists=True)

    # DB-04: Drop constraints
    op.drop_constraint("chk_expenses_positive_amount", "expenses", type_="check")
    op.drop_constraint("chk_patients_commission_range", "patients", type_="check")
    op.drop_constraint("chk_patients_discount_le_total", "patients", type_="check")
    op.drop_constraint("chk_patients_positive_amounts", "patients", type_="check")

