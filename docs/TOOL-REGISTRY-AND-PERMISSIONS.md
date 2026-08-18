# Versioned Tool Registry and default-deny ToolGrant contract

`src/futures_agent_os/governance_registry/tool_registry.py` is the immutable V0 Tool Registry. Both the Registry and every `ToolVersion` have an explicit `major.minor` version; resolution accepts only an exact `tool_id@major.minor` reference and never `latest`. There is no implementation activation, tool execution, model invocation, database access, order routing, or trading side effect in this task.

`src/futures_agent_os/agent_orchestration/tool_permissions.py` is the deterministic pre-invocation authorization boundary. It evaluates a proposed `ToolCallRequest` against the Registry, the static Agent Catalog declaration, and one or more explicit `ToolGrant` records. A catalog declaration is not a grant; a grant is not an activation; a permitted result is not tool execution.

## Permission hierarchy

| Contract tier | Tool capability class | V0 meaning |
|---|---|---|
| `READ_ONLY` | T0/T1 queries | Read static or sensitive facts through a future Gateway. |
| `RESEARCH_REQUEST` | T2 | Request a bounded, non-side-effect research job. |
| `PROPOSAL` | T3 | Create a draft or governed proposal only. |
| `MANDATE_SCOPED_SIMULATION` | T4-OPEN boundary | Request the separate simulation authorization path; it does not replace its Mandate/Basis/receipt/RiskDecision checks. |
| `PLAN_APPROVAL` | T4-ESCALATED request | Request an optional one-plan approval; it is not an approval itself. |
| `PROMOTION` | T5 promotion request | Submit a governed promotion proposal; qualification remains separate. |
| `ACTIVATION` | T5 activation request | Request governed activation; the Registry decides no activation in V0. |

A grant names exact ToolVersions and has a maximum tier. A request must also be declared for its exact Agent Catalog role/version. Within the operational `READ_ONLY` through `PLAN_APPROVAL` family, a higher tier can cover a lower tier only for the same explicit ToolVersion and scope. `PROMOTION` and `ACTIVATION` are separate governance families and never inherit trading capability; no Grant creates a wildcard ability.

## Scope and rejection semantics

Every grant binds an Agent role and a worker node, and supports account, strategy, instrument, policy-version, governed-artifact-version, and isolated environment selectors. Calls may never widen a non-empty selector. `MANDATE_SCOPED_SIMULATION` and `PLAN_APPROVAL` Grants must explicitly bound account, strategy, instrument, policy, and environment. `PROMOTION` and `ACTIVATION` Grants instead must bound governed artifact, policy, and environment, without inventing irrelevant account/instrument constraints for Agent, Model, Prompt, or Toolset governance. Only `local`, `test`, `staging`, and `sim_prod` are representable; real-money environments are absent.

Authorization is default-deny. Every attempt returns an immutable `ToolAuthorizationDecision` with call/correlation IDs, Agent role, node, exact ToolVersion, a deterministic request SHA-256 fingerprint, a stable `ReasonCode`, evaluation time, and, only for permits, the matched ToolGrant ID. The evaluation order is fixed: exact Registry/version, Agent Catalog role/version/declaration, active/non-expired role grant, node, exact ToolVersion, tier, and full scope. Thus unauthorized, forged, expired, cross-scope, and Registry/Catalog/Tool version-drift attempts reject without throwing an authorization exception or calling a tool.

## Non-substitutable authority facts

`ToolGrant` deliberately has no `mandate_id`, `plan_approval_id`, `risk_decision_id`, or `activation_id`. These remain distinct:

- `SimulationAutonomyMandate`, `AuthorizationBasis`, `PlanApproval`, and `AutonomyGateReceipt` belong to Decision and govern a specific simulation business path.
- `RiskDecision` and `ProtectionMandate` belong to Portfolio & Risk.
- Promotion and Activation are Governance & Registry decisions.
- `ToolGrant` only controls whether an Agent/node may request a versioned Tool capability in a narrow scope.

Later deterministic application services must perform their own Mandate/Basis/receipt/RiskDecision/activation checks after this pre-invocation contract permits a request. A ToolGrant can never turn a draft into authority, execute a tool, expand a Mandate, consume a PlanApproval, or activate a governed artifact. `ToolAuthorizer` receives a trusted snapshot from the future Governance & Registry ToolGrant repository; a deserialized `ToolGrant` dataclass carries no signature or origin proof by itself. Repository authentication, persistence, and tamper-evidence are deliberately future infrastructure work, not claimed by this V0 static contract.
