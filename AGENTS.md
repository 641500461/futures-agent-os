# Project working agreement

Before changing this repository, read `docs/HANDOFF.md`, `docs/ROADMAP.md`, and the design sections referenced by the active Roadmap task.

- This is a greenfield project. Do not import from, write to, or depend at runtime on `/Users/qiu/futures_workflow`.
- Work on one explicitly authorized Roadmap task at a time. Do not mark it complete until its Acceptance is proven by reproducible Evidence.
- Preserve the research-and-simulation-only boundary. Real-money trading and real order routing are out of scope.
- Deterministic domain services own market/account/risk/order/fill/ledger truth. Agent output is a proposal, never authority.
- Keep business state and Agent checkpoint state separate.
- Add or update tests before marking behavior complete.
- Update `docs/ROADMAP.md` and `docs/HANDOFF.md` whenever a task changes status.

