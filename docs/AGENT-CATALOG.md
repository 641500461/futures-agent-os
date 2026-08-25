# Versioned Agent Catalog and bounded collaboration protocol

Version: `1.4`
Status: V1-009 catalog contract

`src/futures_agent_os/agent_orchestration/catalog.py` is the machine-readable source of this catalog. It defines the twelve logical roles, their version, enablement version, responsibility boundary, all six trigger origins, input/output artifact types, declared tools, budget, failure disposition and metrics. It is not an activation record or an executable permission grant.

| Role | Enabled from | Primary output | Failure disposition |
| --- | --- | --- | --- |
| Main / Autonomous Quant PM | V1 | `research_brief`, `decision_digest` | `DEFER` |
| Market Regime | V1 | `market_state_assessment` | `DEFER` |
| Research | V1 | `hypothesis`, `evidence_synthesis`, `experiment_request` | `KEEP_DRAFT` |
| Strategy | V3 | `strategy_candidate`, `trade_plan_draft` | `DEFER` |
| Portfolio | V3 | `portfolio_proposal` | `FAIL_CLOSED` |
| Risk Analyst | V3 | `risk_assessment` | `FAIL_CLOSED` |
| Execution Advisor | V3 | `execution_recommendation` | `FALLBACK_READ_ONLY` |
| Pre-trade Critic | V1 | `critique` | `FAIL_CLOSED` |
| Experiment Manager | V1 | `experiment_plan` | `KEEP_DRAFT` |
| Post-trade Reviewer | V3 | `trade_review`, `reflection` | `KEEP_PENDING_REVIEW` |
| Memory Curator | V4 | `lesson_candidate` | `KEEP_EXISTING_STATE` |
| Governance | V4; Steward mode V5 | `change_proposal` | `QUARANTINE_CANDIDATE` |

Every role documents user, schedule, market, explicit `DATA`, account/position and system/lifecycle trigger origins. The exact examples are intentionally broad: the deterministic Workflow Orchestrator determines whether a concrete trigger creates a task, enforces lifecycle, retries, cancellation, deadline and recovery. In V1-008 Main coordinates only the observe/research graph; it neither schedules work, grants authority, nor creates `TradePlan`/`StrategyCandidate`. No role is a permanent process merely by existing in this catalog.

In V1-009 Pre-trade Critic is strictly a research-artifact adapter. It consumes only exact `hypothesis`, `evidence_synthesis`, and `experiment_request` identities, emits one `critique`, and invokes no tools. V1-010 deterministic diagnostic artifacts do not yet exist, so V1-009 rejects caller diagnostics and emits the fixed closed eight-category `GAP`/`UNRESOLVED` set (with `DATA_LEAKAGE` HIGH), fixed validation codes, and `DEFER`; it never claims `CLEAR`, `RESOLVED`, `PASS`, or `REJECT`. Catalog 1.3 remains separately resolvable for historical replay and is not reinterpreted under this contract.

## Contract boundaries

- `AgentTaskEnvelope` has a catalog version, finite budget, explicit completion definition, input/policy artifact references, `as_of`, expiry, output schema and declared tool subset. `validate_task_envelope` rejects a role/version/input/tool/output mismatch or any budget dimension above the catalog cap before dispatch; duplicate trigger, tool and output declarations are invalid.
- `ArtifactRef` is content-addressed (`sha256:`), schema-versioned and time-bounded. `StructuredArtifact` and `SpecialistResult` preserve source references, evidence-backed claims, warnings, uncertainty and expiry.
- `AgentHandoff` is one-way and routed by the orchestrator. It transfers immutable references and an explicit authorization boundary, never a mutable business object, a DB handle, a tool grant, or free-form peer chat.
- Task-level tools are only catalog declarations. V0 does not resolve Tool Grants, activation bindings, account scope, autonomy mandates, model calls, or any trading action; V0-006 and later deterministic contexts own those decisions.
- Conflicts are not decided by majority vote. Data facts return to deterministic data tools; Critic blocks/requires evidence, Portfolio can only reduce/reject exposure, and Risk Constitution/AutonomyGate remain superior to every Agent artifact.
