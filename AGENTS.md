# Project working agreement

Before changing this repository, read `docs/HANDOFF.md`, `docs/ROADMAP.md`, and the design sections referenced by the active Roadmap task.

Route implementation and review work according to `docs/DEVELOPMENT-MODEL-POLICY.md`, and record the actual model and reasoning effort in task Evidence.

- This is a greenfield project. Do not import from, write to, or depend at runtime on `/Users/qiu/futures_workflow`.
- Work on one explicitly authorized Roadmap task at a time. Do not mark it complete until its Acceptance is proven by reproducible Evidence.
- Assume a single-user, locally controlled, trusted-operator deployment. Do not create or expand Roadmap scope for adversarial local tamper resistance, evidence signing/re-hash defense, multi-user RBAC, tenant isolation, zero-trust infrastructure, or similar security hardening unless the user explicitly authorizes it or the deployment boundary changes.
- This security de-scoping does not relax the research-and-simulation-only boundary, deterministic trading correctness, risk/account/order/fill/ledger invariants, idempotency/concurrency/recovery, reproducible research, or basic credential hygiene. Never commit or log secret values, and do not give untrusted code unrestricted host access.
- Preserve the research-and-simulation-only boundary. Real-money trading and real order routing are out of scope.
- Deterministic domain services own market/account/risk/order/fill/ledger truth. Agent output is a proposal, never authority.
- Keep business state and Agent checkpoint state separate.
- Add or update tests before marking behavior complete.
- Update `docs/ROADMAP.md` and `docs/HANDOFF.md` whenever a task changes status.
