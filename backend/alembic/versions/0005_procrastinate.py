"""procrastinate: install the task-queue schema

Revision ID: 0005_procrastinate
Revises: 0004_graph
Create Date: 2026-06-26

Installs Procrastinate's queue schema (procrastinate_* tables, types, functions,
triggers) from SchemaManager.get_schema(). The app's `jobs` table remains the
status-of-record; this is the internal executor queue. Downgrade drops every
object prefixed procrastinate_.
"""

from alembic import op
from procrastinate.schema import SchemaManager
from sqlalchemy.util import await_only

revision = "0005_procrastinate"
down_revision = "0004_graph"
branch_labels = None
depends_on = None

_DROP = r"""
DO $$
DECLARE r record;
BEGIN
    FOR r IN SELECT tablename FROM pg_tables
             WHERE schemaname = 'public' AND tablename LIKE 'procrastinate\_%' LOOP
        EXECUTE format('DROP TABLE IF EXISTS public.%I CASCADE', r.tablename);
    END LOOP;
    FOR r IN SELECT oid::regprocedure AS sig FROM pg_proc
             WHERE pronamespace = 'public'::regnamespace AND proname LIKE 'procrastinate\_%' LOOP
        EXECUTE 'DROP FUNCTION IF EXISTS ' || r.sig || ' CASCADE';
    END LOOP;
    FOR r IN SELECT typname FROM pg_type
             WHERE typnamespace = 'public'::regnamespace
               AND typname LIKE 'procrastinate\_%' AND typtype IN ('c', 'e') LOOP
        EXECUTE format('DROP TYPE IF EXISTS public.%I CASCADE', r.typname);
    END LOOP;
END $$;
"""


def _run(sql: str) -> None:
    raw = op.get_bind().connection.driver_connection
    await_only(raw.execute(sql))


def upgrade() -> None:
    _run(SchemaManager.get_schema())


def downgrade() -> None:
    _run(_DROP)
