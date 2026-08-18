# Datasets

Only synthetic data and versioned manifests belong in Git. Market data and research artifacts must use the lineage and licensing rules defined in the design package.

## V0-012 synthetic golden market data

`v0-012/` is a deterministic, synthetic, low-frequency fixture. It establishes
data and replay contracts; it is not a real market-data feed and makes no
tick/order-book, fill, or execution-fidelity claim.

It contains four committed assets:

- `golden_market_events.jsonl`: source-arrival ordered normalized PIT observations.
- `golden_market_events.manifest.json`: the immutable dataset descriptor,
  including synthetic provenance, CC0 terms, schema, coverage, quality, hash,
  revision, and generator identity.
- `cases.json`: the product rationale and expected boundary handling for each
  scenario. It is explanatory metadata, not a trading rule; its hash and
  provenance are independently bound by the bundle manifest.
- `golden_bundle.manifest.json`: binds the events, events-manifest, and catalog
  hashes, plus its own bundle identity/version/revision and synthetic provenance
  for independent delivery. It deliberately does not form a hash cycle: the
  events manifest does not point back to the bundle.

The acceptance universe is `AG`, `CU`, `RB`, `JM`, `I`, `MA`, `SA`, `M`, `P`,
`SR`, `SC`, and `JD`. The fixture covers night-session trading-date attribution,
rule changes, upper- and lower-price limits, gaps, no liquidity, source-arrival disorder, and
missing data; it also includes margin, close-today fee, near-delivery,
settlement-anomaly, and correlation-stress markers for later deterministic
contracts.

The JSONL is globally ordered by `available_time` (source arrival), while the
MA late-event fixture intentionally has reversed `event_time`/sequence within
that arrival order. All timestamps are UTC except the explicit `market_time` display field. A
night-session record supplies `trading_date` directly; consumers must not infer
it from its calendar date. Every record has `event_time` and `available_time`,
so point-in-time use must respect `available_time <= as_of`.

Regenerate and validate with:

```bash
uv run python scripts/generate_v0_012_golden_datasets.py
uv run pytest tests/contract/test_golden_datasets.py
```

The generator uses only fixed inputs and canonical JSON, so it must reproduce
the committed bytes exactly. A fixed release oracle outside the generator locks
the released dataset and bundle lineages, events digest, events-manifest digest,
catalog digest, and bundle digest. The contract tests reject changed hashes, manifest
drift, future availability, missing universe members, incomplete product
rationale, or any missing required boundary case.

V0-012 intentionally implements the narrower Roadmap acceptance only. The
broader examples in TECH §18.3—holiday calendars, continuous-contract rolls,
late *ticks*, partial fills, and other execution/settlement behaviors—remain
future-version fixtures; this low-frequency dataset neither fabricates them nor
claims their semantics. Its MA record is a late normalized event, not a tick.
