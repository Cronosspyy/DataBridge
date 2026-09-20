-- Read-only role for the deployed app.
--
-- The app sends LLM-generated SQL to the database. src/sql_validator.py is a
-- best-effort text filter and should not be the only thing preventing a write,
-- so the connection string used in production points at this role instead of
-- the owner. A generated INSERT or DROP then fails at the database, whatever
-- the validator happened to think of it.
--
-- Run this once as the database owner, then use databridge_readonly in
-- DATABASE_URL.

CREATE ROLE databridge_readonly LOGIN PASSWORD 'change-me-before-running';

-- Can see the schema, cannot create anything in it.
GRANT CONNECT ON DATABASE databridge TO databridge_readonly;
GRANT USAGE ON SCHEMA public TO databridge_readonly;

-- SELECT on the four tables, and nothing else.
GRANT SELECT ON ALL TABLES IN SCHEMA public TO databridge_readonly;

-- Same for any table added later.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON TABLES TO databridge_readonly;

-- Belt and braces: every transaction this role opens is read-only, so even a
-- statement the grants would have allowed cannot write.
ALTER ROLE databridge_readonly SET default_transaction_read_only = on;

-- Cap runaway queries at the role level, independent of the application.
ALTER ROLE databridge_readonly SET statement_timeout = '5s';
