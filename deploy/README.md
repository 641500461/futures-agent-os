# Deployment

The approved deployment is a trusted, single-user local research/simulation run. Start with `uv run futures-agent-os trial --at <UTC-ISO-TIMESTAMP>`; this path uses synthetic deterministic facts and has no real-market or real-order side effects. The Feishu gateway remains separately available through `uv run futures-agent-os gateway run` when its configured database and credentials are present.

Long-running HA/DR, 30-day stability and full non-empty-state PITR are explicitly deferred and are not prerequisites for this local trial.
