# Domain Boundary Baseline

本基线把 `CONTEXT-MAP.md` 的领域边界固化为可检查的唯一所有权清单。它只声明业务事实的权威拥有者；跨上下文只能发布不可变事实、稳定标识或版本化引用，不能转移或共享写权限。

## Context roster

| Context | Classification | Context document |
| --- | --- | --- |
| Reference Market Data | core | `docs/contexts/reference-market-data/CONTEXT.md` |
| Market Intelligence | core | `docs/contexts/market-intelligence/CONTEXT.md` |
| Research & Experiment | core | `docs/contexts/research-experiment/CONTEXT.md` |
| Decision | core | `docs/contexts/decision/CONTEXT.md` |
| Portfolio & Risk | core | `docs/contexts/portfolio-risk/CONTEXT.md` |
| Execution & Simulation | core | `docs/contexts/execution-simulation/CONTEXT.md` |
| Accounting & Settlement | core | `docs/contexts/accounting-settlement/CONTEXT.md` |
| Learning & Review | core | `docs/contexts/learning-review/CONTEXT.md` |
| Governance & Registry | core | `docs/contexts/governance-registry/CONTEXT.md` |
| Agent Orchestration | supporting | `docs/contexts/agent-orchestration/CONTEXT.md` |

## Aggregate ownership

| Aggregate | Authoritative context | Boundary assertion |
| --- | --- | --- |
| Simulation Autonomy Mandate | Decision | A long-lived user delegation; neither orchestration nor governance may create, widen, or replace it. |
| Autonomy Mode Binding | Decision | A runtime-mode binding, not a Mandate lifecycle, system-health state, or governance activation. |
| Authorization Basis | Decision | The plan-specific authorization reference; it is not a Risk Decision, Tool Grant, or agent authority. |
| Autonomy Gate Receipt | Decision | A short-lived single-use gate result; it is not an authorization basis or Risk Decision. |
| Risk Budget Reservation | Portfolio & Risk | An atomic temporary allocation; it is neither account funds nor authorization. |
| Risk Decision | Portfolio & Risk | The Risk Constitution's plan-specific risk ruling; it never substitutes for authorization. |
| Protection Mandate | Portfolio & Risk | The protection requirements implied by a Risk Decision; it is not an execution policy. |
| Risk Reduction Request | Decision | An immutable intent to reduce existing exposure, not proof of safe reduction and not an order. |
| Risk Reduction Validation | Execution & Simulation | The deterministic T4-SAFE validation of a reduction request or protection trigger. |
| Protective Risk Action | Execution & Simulation | An idempotent protective execution fact that cannot reverse exposure or relax protection. |
| Order | Execution & Simulation | A simulated venue execution object; agents and Decision never create it directly. |
| Fill | Execution & Simulation | An immutable simulated execution fact; it is not a Position or ledger entry. |
| Position | Accounting & Settlement | The current instrument exposure and accounting quantity derived from fills and settlement. |
| Ledger | Accounting & Settlement | The complete account financial and position-change fact set. |
| Decision Journal | Learning & Review | An append-only, rebuildable projection; source business facts retain their original owners. |
| Trade Episode | Learning & Review | A rebuildable cross-context projection that never acquires source-object write authority. |

## Boundary invariants

- Every aggregate in this document has exactly one authoritative context.
- A supporting context may coordinate commands and retain process records, but cannot own a listed business aggregate.
- `Position` and `Ledger` are accounting truth. Execution publishes `Fill`; Portfolio & Risk consumes position/account snapshots.
- `Risk Reduction Validation` must precede `Protective Risk Action`; a rejected or stale validation creates no action.
- `Decision Journal` and `Trade Episode` are projections only. They append or rebuild from published source facts and cannot write back to their sources.
- No aggregate in this baseline grants authority outside its own boundary: a Mandate, Mode Binding, Authorization Basis, Receipt, Risk Decision, and Protection Mandate remain distinct facts.
