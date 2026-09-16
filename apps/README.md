# Runtime applications

The current operator entry points are `uv run futures-agent-os trial` for a one-shot local journey and `uv run futures-agent-os gateway run` for the Feishu long connection plus its bounded inbound-command and outbox workers. The gateway command surface is intentionally limited to status, one synthetic deterministic simulation, and restart-safe review; signed control callbacks remain separate.

Independent `agent_worker`, `research_worker`, `trading_worker`, `market_ingest`, `scheduler`, and `outbox_sender` process supervision remains later deployment-composition work and is not required for the approved single-user local trial.
