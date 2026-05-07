# Database migrations

This directory contains plain SQL migrations. The files use the
golang-migrate naming convention:

1. `000001_enable_pgvector.up.sql`
2. `000002_core_chat_tables.up.sql`
3. `000003_message_outbox.up.sql`
4. `000004_memory.up.sql`
5. `000005_memory_lifecycle.up.sql`
6. `000006_memory_embedding_recall.up.sql`

Run migrations in numeric order. Rollbacks should use the matching `.down.sql`
files in reverse numeric order.

## Local psql

For a fresh local database, run:

```sh
psql "$DATABASE_URL" -f database/migrations/000001_enable_pgvector.up.sql
psql "$DATABASE_URL" -f database/migrations/000002_core_chat_tables.up.sql
psql "$DATABASE_URL" -f database/migrations/000003_message_outbox.up.sql
psql "$DATABASE_URL" -f database/migrations/000004_memory.up.sql
psql "$DATABASE_URL" -f database/migrations/000005_memory_lifecycle.up.sql
psql "$DATABASE_URL" -f database/migrations/000006_memory_embedding_recall.up.sql
```

To roll back the initial schema:

```sh
psql "$DATABASE_URL" -f database/migrations/000006_memory_embedding_recall.down.sql
psql "$DATABASE_URL" -f database/migrations/000005_memory_lifecycle.down.sql
psql "$DATABASE_URL" -f database/migrations/000004_memory.down.sql
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

## Chat persistence

Migration `000002_core_chat_tables` creates the durable chat history used by
Brain message persistence:

- `conversations`
- `message_events_raw`
- `messages`
- `bot_responses`

When `DATABASE_URL` is set, Brain writes normalized incoming messages and bot
responses into these tables. The Gateway still does not write to the database.

## Memory

Migration `000004_memory` adds the first memory schema:

- `memory_items`: long-term memories with `group`, `user`, `relationship`, and
  `global` scopes.
- `memory_embeddings`: optional semantic vectors using `vector(1536)`.
- `memory_runs`: batch extraction run audit records.
- `memory_settings`: per-group memory enable/disable state.

Memory deletes are soft deletes via `status='deleted'`. The intended production
policy is raw chat history for 30 days and long-term memory until an admin
forget command removes it.

Migration `000005_memory_lifecycle` adds lifecycle and quality fields used by
AI memory recall, including `memory_class`, `lifecycle_status`, `stability`,
`decay_score`, `source_count`, and `quality_score`.

Migration `000006_memory_embedding_recall` adds embedding freshness metadata,
the `(memory_id, embedding_model)` uniqueness rule, and the pgvector recall
index used by hybrid memory recall.
