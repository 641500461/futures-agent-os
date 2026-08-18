# Migrations

V0-007 uses Alembic and PostgreSQL only. It must never contain an implicit import
or migration of the donor database, and the product has no SQLite persistence mode.

The initial baseline is reversible only for the empty-database acceptance exercise.
Later production changes follow `expand → migrate → contract`; corrective changes
are new forward migrations, not rewrites of deployed business history.

`fao` contains business current state, commands, events, inbox/outbox, leases,
schedules, notifications, approvals, and audit indexes. `agent_checkpoint` is a
separately owned schema for durable orchestration state only, never business truth.

Run this initial migration as an isolated database bootstrap identity with
`CREATEROLE` plus permission to create schemas and tables (the local/CI runbook
uses the disposable `postgres` superuser). It creates only non-login group roles.
Production application login identities must be provisioned separately and granted
only their matching group role; they must not be schema owners or `fao_migrator`.

The Alembic version table remains in `public`. Alembic creates it before the first
revision runs, then this migration revokes `PUBLIC` schema creation. Its empty-db
downgrade restores that default grant so the same database can upgrade, downgrade,
and re-upgrade. Do not use this baseline downgrade against a database that contains
other application objects in `public`.

Set `FAO_DATABASE_URL` to an isolated PostgreSQL URL:

```bash
uv run alembic upgrade head
uv run alembic downgrade base
uv run alembic upgrade head
```

For the pinned local container and the same exercise:

```bash
./scripts/postgres_v0_007.sh start
./scripts/postgres_v0_007.sh exercise
./scripts/postgres_v0_007.sh stop
```

Future tables, sequences, functions, and schemas must receive explicit grants in
their own migration. Do not introduce broad `ALTER DEFAULT PRIVILEGES` grants:
each new object must state which service group may read, write, or administer it.

CI uses the same pinned PostgreSQL image in
`.github/workflows/postgresql.yml`; its `FAO_DATABASE_URL` makes the integration
round-trip test mandatory rather than skipped.
