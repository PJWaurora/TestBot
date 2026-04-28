# Database migrations

This directory contains plain SQL migrations. The files use the
golang-migrate naming convention:

1. `000001_enable_pgvector.up.sql`
2. `000002_core_chat_tables.up.sql`
3. `000003_message_outbox.up.sql`

Run migrations in numeric order. Rollbacks should use the matching `.down.sql`
files in reverse numeric order.

## Local psql

For a fresh local database, run:

```sh
psql "$DATABASE_URL" -f database/migrations/000001_enable_pgvector.up.sql
psql "$DATABASE_URL" -f database/migrations/000002_core_chat_tables.up.sql
psql "$DATABASE_URL" -f database/migrations/000003_message_outbox.up.sql
```

To roll back the initial schema:

```sh
psql "$DATABASE_URL" -f database/migrations/000003_message_outbox.down.sql
psql "$DATABASE_URL" -f database/migrations/000002_core_chat_tables.down.sql
psql "$DATABASE_URL" -f database/migrations/000001_enable_pgvector.down.sql
```

## Docker Postgres

When Postgres is running in Docker, execute these same files against the
container database. With a migration runner such as golang-migrate, mount this
directory into the runner container and point it at the Postgres connection
string. With plain `psql`, copy or mount the SQL files and run them in the same
order shown above.

The pgvector extension must be available in the Postgres image before
`000001_enable_pgvector.up.sql` can succeed.

## Re-running migrations

These SQL files are intended to be tracked by a migration runner, which records
which versions have already been applied. Do not repeatedly run the table
creation migration against the same database without resetting or rolling back;
`CREATE TABLE` statements are intentionally not written as `IF NOT EXISTS` so
schema drift fails loudly.

The pgvector migration uses `CREATE EXTENSION IF NOT EXISTS` so it is safe if
the extension was already enabled by a previous setup step.

## Embeddings

Embedding tables are intentionally not included yet. Add them after the
embedding model and vector dimensions are chosen, so the vector column can be
declared with the correct dimension.
