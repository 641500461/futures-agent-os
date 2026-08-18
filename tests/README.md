# Test suites

The project separates `unit`, `contract`, `integration`, `replay`, `fault`, and `agent_eval` evidence.

`tests/integration/test_postgresql_migration_round_trip.py` is a real PostgreSQL
acceptance test. It is skipped unless `FAO_DATABASE_URL` points to a disposable,
empty PostgreSQL database; it never substitutes SQLite. Use
`./scripts/postgres_v0_007.sh exercise` for the local round trip.
