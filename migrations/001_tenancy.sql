-- Gate G initial tenancy / RBAC / audit schema.
-- Dialect: SQLite-compatible subset also intended for Postgres (TEXT timestamps, no JSONB).
-- Applying this file does NOT make Gate G complete without live Postgres isolation drills.

CREATE TABLE IF NOT EXISTS tenants (
  tenant_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS principals (
  principal_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  email TEXT NOT NULL,
  role TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (tenant_id, email)
);

CREATE TABLE IF NOT EXISTS audit_events (
  audit_id TEXT PRIMARY KEY,
  tenant_id TEXT,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  allowed INTEGER NOT NULL,
  detail TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS run_index (
  run_id TEXT PRIMARY KEY,
  tenant_id TEXT,
  source TEXT,
  verdict TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schema_migrations (
  version TEXT PRIMARY KEY,
  applied_at TEXT NOT NULL
);
