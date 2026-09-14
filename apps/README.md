# Runtime applications

The current operator entry point is `uv run futures-agent-os trial`, which exercises the complete research-to-simulation journey in one local process. Planned long-running boundaries remain `gateway`, `agent_worker`, `research_worker`, `trading_worker`, `market_ingest`, `scheduler`, and `outbox_sender`; they are deployment composition work and are not required for the approved single-user local trial.
