# MVP-R-003 Research Episode fixture-episode-001

Execution mode: `FIXTURE_RENDER_ONLY`

This report is research and simulation only. It is not a trade, order, position, risk decision, fill, or ledger fact.

## Experiment-pre judgment

- Instrument / cutoff: `CU` / `2025-05-30T15:00:00Z`
- Selected hypothesis: signal accuracy exceeds the inverted-direction control
- Falsification condition: reject if stressed or counterfactual evidence removes the registered advantage

## Independent Critic

- `SELECT`: FIXTURE_BOUNDED_BUT_NOT_DISCOVERY_EVIDENCE

## Deterministic experiment results

- `l0_signal_test`: `signal_accuracy=0.60000000`, `counterfactual_signal_accuracy=0.40000000`
- `l1_bar_backtest`: `proxy_net_return=0.04000000`
- `walk_forward_test`: `positive_fold_ratio=0.66666667`
- `cost_slippage_stress`: `stressed_net_return=0.03000000`
- `counterfactual_test`: `counterfactual_stressed_net_return=-0.05000000`

## Experiment-post judgment

- Verdict: `ACCEPT`
- Rationale: Fixture metrics support the registered comparison.
- Result reference: `experiment-result://fixture-episode-001-fixture-packet/78cd3edc1af268c5761b0e715aad9fd5f19c7c1e42bc932ddf352f818751944f`

## Limitations

- render fixture; no Discovery experiment was executed
