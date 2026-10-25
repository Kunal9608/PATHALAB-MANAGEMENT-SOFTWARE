"""admin_important_documents_vault

Revision ID: 9c0d1e2f3a4b
Revises: 8b9c0d1e2f3a
Create Date: 2026-10-25 12:00:00.000000

Creates admin_vault_items table for private, encrypted administrator documents and notes.
Enforces Row Level Security (RLS) and strict per-admin isolation.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '9c0d1e2f3a4b'
down_revision: Union[str, Sequence[str], None] = '8b9c0d1e2f3a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'admin_vault_items',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('admin_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('item_type', sa.String(length=20), server_default='document', nullable=False),
        sa.Column('category', sa.String(length=50), server_default='general', nullable=False),
        sa.Column('title_encrypted', sa.Text(), nullable=False),
        sa.Column('title_hint', sa.String(length=100), nullable=True),
        sa.Column('storage_path', sa.String(length=255), nullable=True),
        sa.Column('content_encrypted', sa.Text(), nullable=True),
        sa.Column('file_size_bytes', sa.Integer(), nullable=True),
        sa.Column('mime_type', sa.String(length=100), nullable=True),
        sa.Column('encryption_metadata', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['admin_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_admin_vault_items_admin_id'), 'admin_vault_items', ['admin_id'], unique=False)
    op.create_index(op.f('ix_admin_vault_items_category'), 'admin_vault_items', ['category'], unique=False)
    op.create_index(op.f('ix_admin_vault_items_item_type'), 'admin_vault_items', ['item_type'], unique=False)

    # Enable Row-Level Security (RLS) on admin_vault_items table
    op.execute("ALTER TABLE public.admin_vault_items ENABLE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE POLICY admin_vault_items_isolation_policy ON public.admin_vault_items
            FOR ALL
            USING (
                admin_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
                OR current_user IN ('postgres', 'service_role')
            )
            WITH CHECK (
                admin_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
                OR current_user IN ('postgres', 'service_role')
            );
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS admin_vault_items_isolation_policy ON public.admin_vault_items;")
    op.drop_index(op.f('ix_admin_vault_items_item_type'), table_name='admin_vault_items')
    op.drop_index(op.f('ix_admin_vault_items_category'), table_name='admin_vault_items')
    op.drop_index(op.f('ix_admin_vault_items_admin_id'), table_name='admin_vault_items')
    op.drop_table('admin_vault_items')
