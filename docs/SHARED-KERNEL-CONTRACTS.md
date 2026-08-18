# Shared Kernel Contracts

V0-004 defines the small set of values that may cross bounded-context boundaries. They are immutable, serializable primitives; business aggregates remain owned by their contexts.

## Identifiers

`EntityId` is an opaque UUIDv7 identifier serialized as `<lower_snake_case namespace>_<uuidv7>`. The namespace records the kind of referenced fact without making another context depend on that fact's mutable representation. IDs are never reused or rewritten.

## Exact numeric values

`Money`, `Price`, and `Quantity` require an explicit decimal scale from 0 through 18. They accept only `Decimal`, `int`, or decimal text; binary `float`, non-finite values, values more precise than the declared scale, and values that cannot be represented at that scale are rejected. JSON represents the amount as a string so the scale and exact value survive a round trip.

`Money` carries ISO-4217 currency. `Price` carries quote currency and an economic unit. `Quantity` carries its economic unit. Consumers must not infer a currency or unit from a field name or environment default.

## Time

`RecordedAt` is always persisted and serialized in UTC. `ShanghaiTimestamp` is a market-facing timestamp expressed using the `Asia/Shanghai` IANA timezone. `TradingDate` is a calendar-assigned business date, not a conversion of a timestamp: the Reference Market Data Trading Calendar will assign night-session and holiday attribution in V1.

## Schema and failures

Artifacts, events, tools, and APIs use canonical `major.minor` `SchemaVersion` values. Schema evolution follows the existing forward-only, explicit-version policy.

`ReasonCode` is the machine contract for deterministic failures. Human text belongs in the optional `Failure.message` and must never be parsed for control flow. New codes are additive enum members; an existing code's spelling or meaning is not changed.
