"""Frozen strategy fixture replay bridge for shared simulation qualification."""

from dataclasses import dataclass
from typing import Any, cast
from decimal import Decimal

from futures_agent_os.research_experiment.walk_forward import OosFoldEvaluation, evaluate_oos_folds, fold_manifest_json
from futures_agent_os.shared_kernel import canonical_sha256
from futures_agent_os.accounting_settlement import AccountingEvent, AccountingEventLog, SimulationAccount
from futures_agent_os.decision import Order, OrderStatus, TradeDirection
from futures_agent_os.shared_kernel import EntityId, RecordedAt
from futures_agent_os.shared_kernel.observability import JsonValue
from futures_agent_os.execution_simulation.l2_model import BookEvent
from datetime import UTC, datetime
from .engine import SimulationEngine
from futures_agent_os.research_experiment.mvp_replay import ReplayEpisodeCandidate


@dataclass(frozen=True, slots=True)
class L2ReplayResult:
    fixture_hash: str
    variant: str
    order_ids: tuple[str, ...]
    fill_ids: tuple[str, ...]
    ledger_cash: str
    replay_cash: str
    position_quantity: str
    result_hash: str


@dataclass(frozen=True, slots=True)
class L2ReplayMatrix:
    fixture_hash: str
    variants: tuple[L2ReplayResult, ...]
    matrix_hash: str

    @property
    def deterministic(self) -> bool:
        return len(self.variants) == 3 and all(item.ledger_cash == item.replay_cash for item in self.variants)


@dataclass(frozen=True, slots=True)
class FrozenStrategySpecFixture:
    fixture_id: str
    version: int
    signals: tuple[int, ...]
    labels: tuple[int, ...]
    forward_returns: tuple[Decimal, ...]
    signal_times: tuple[str, ...]
    label_times: tuple[str, ...]
    per_signal_cost: Decimal
    train_bars: int
    test_bars: int
    step_bars: int
    embargo_bars: int

    @classmethod
    def from_mvp_replay_candidate(
        cls,
        candidate: ReplayEpisodeCandidate,
        *,
        per_signal_cost: Decimal = Decimal("0.00030000"),
        signal_threshold: Decimal = Decimal("0.00010000"),
    ) -> "FrozenStrategySpecFixture":
        """Adapt a sealed V1 MVP-R PIT candidate into the shared replay fixture.

        The candidate contains the forty-bar future-blind window and the one
        revealed future bar selected by :mod:`mvp_replay`.  We derive the
        exact V1 prior-close signal/next-close label arrays from those records,
        then let the V2 L2 engine execute the resulting signals.  No synthetic
        prices or labels are introduced by this bridge.
        """
        if type(candidate) is not ReplayEpisodeCandidate:
            raise TypeError("V1 replay bridge requires a ReplayEpisodeCandidate")
        if type(per_signal_cost) is not Decimal or per_signal_cost < 0:
            raise ValueError("per_signal_cost must be a non-negative Decimal")
        if type(signal_threshold) is not Decimal or signal_threshold < 0:
            raise ValueError("signal_threshold must be a non-negative Decimal")
        records = (*candidate.records, candidate.future_record)
        closes = tuple(Decimal(str(item.values["close"])) for item in records)
        if any(value <= 0 for value in closes):
            raise ValueError("V1 replay bridge requires positive close values")
        returns = tuple(closes[index] / closes[index - 1] - 1 for index in range(1, len(closes)))
        signals = tuple(
            1 if value > signal_threshold else -1 if value < -signal_threshold else 0 for value in returns[:-1]
        )
        labels = tuple(1 if value > 0 else -1 if value < 0 else 0 for value in returns[1:])
        signal_times = tuple(records[index + 1].event_time.to_dict()["recorded_at"] for index in range(len(signals)))
        label_times = tuple(records[index + 2].event_time.to_dict()["recorded_at"] for index in range(len(signals)))
        fixture_id = f"mvp-r:{candidate.instrument_id}:{candidate.market_cutoff.value.isoformat()}"
        return cls(
            fixture_id,
            1,
            signals,
            labels,
            returns[1:],
            signal_times,
            label_times,
            per_signal_cost,
            20,
            10,
            10,
            1,
        )

    def __post_init__(self) -> None:
        if not self.fixture_id or self.version < 1:
            raise ValueError("fixture identity must be explicit")
        if len(self.signals) != len(self.labels) or len(self.signals) != len(self.forward_returns):
            raise ValueError("fixture arrays must be aligned")
        if len(self.signal_times) != len(self.signals) or len(self.label_times) != len(self.signals):
            raise ValueError("fixture timestamps must be aligned")
        if self.per_signal_cost < 0:
            raise ValueError("fixture cost must be non-negative")

    @property
    def fixture_hash(self) -> str:
        return canonical_sha256(
            {
                "id": self.fixture_id,
                "version": self.version,
                "signals": self.signals,
                "labels": self.labels,
                "returns": tuple(str(x) for x in self.forward_returns),
                "signal_times": self.signal_times,
                "label_times": self.label_times,
                "cost": str(self.per_signal_cost),
                "train": self.train_bars,
                "test": self.test_bars,
                "step": self.step_bars,
                "embargo": self.embargo_bars,
            }
        )

    def replay(self) -> tuple[OosFoldEvaluation, ...]:
        return evaluate_oos_folds(
            signals=self.signals,
            labels=self.labels,
            forward_returns=self.forward_returns,
            per_signal_cost=self.per_signal_cost,
            train_bars=self.train_bars,
            test_bars=self.test_bars,
            step_bars=self.step_bars,
            embargo_bars=self.embargo_bars,
            signal_times=self.signal_times,
            label_times=self.label_times,
            config_sha256=self.fixture_hash,
        )

    def manifest(self) -> str:
        return fold_manifest_json(self.replay())

    def counterfactual_manifest(self) -> str:
        """Replay the registered fixture with every signal direction inverted."""
        return self._variant_manifest(tuple(-signal for signal in self.signals), "counterfactual")

    def stressed_manifest(self, *, cost_multiplier: Decimal = Decimal("2")) -> str:
        """Replay a deterministic cost-stress variant without changing labels."""
        if type(cost_multiplier) is not Decimal or cost_multiplier < 0:
            raise ValueError("cost_multiplier must be a non-negative Decimal")
        return self._variant_manifest(
            self.signals,
            f"stress:{cost_multiplier}",
            cost=self.per_signal_cost * cost_multiplier,
        )

    def replay_l2(self, *, variant: str = "base", cost_multiplier: Decimal = Decimal("1")) -> L2ReplayResult:
        """Run the frozen signals through the same L2 order/fill/account path.

        This is deliberately a small qualification fixture, not a production
        backtest scheduler. Each signal emits one deterministic market order;
        the book has enough depth for exactly one lot and the resulting Fill is
        written to an accounting log and replayed into a fresh projection.
        Counterfactual and stress variants therefore change actual L2 facts,
        not merely a configuration hash.
        """
        if variant not in {"base", "counterfactual", "stress"}:
            raise ValueError("unknown L2 replay variant")
        signals = tuple(-x for x in self.signals) if variant == "counterfactual" else self.signals
        account_id = EntityId.deterministic("simulation_account", f"{self.fixture_hash}:{variant}")
        at = RecordedAt.from_datetime(datetime(2026, 1, 2, 8, 0, tzinfo=UTC))
        account = SimulationAccount(Decimal("100000"), account_id=account_id)
        log = AccountingEventLog()
        order_ids: list[str] = []
        fill_ids: list[str] = []
        event_sequence = 0
        for index, signal in enumerate(signals):
            if signal == 0:
                continue
            direction = TradeDirection.LONG if signal > 0 else TradeDirection.SHORT
            order = Order(
                EntityId.deterministic("order", f"{self.fixture_hash}:{variant}:{index}"),
                EntityId.deterministic("execution_plan", f"{self.fixture_hash}:{variant}:{index}"),
                "FIXTURE",
                direction,
                Decimal("1"),
                OrderStatus.WORKING,
                created_at=at,
            )
            # Cost stress is represented in the executable book (adverse
            # spread), while counterfactual changes the actual side.
            spread = Decimal("1") * cost_multiplier
            events = (
                BookEvent(index * 2 + 1, Decimal("99") - spread, Decimal("1"), Decimal("101") + spread, Decimal("1")),
                BookEvent(index * 2 + 2, Decimal("99") - spread, Decimal("1"), Decimal("101") + spread, Decimal("1")),
            )
            result = SimulationEngine().execute_l2(order, events, account, now=at)
            order_ids.append(str(order.order_id))
            if result.fill is not None:
                fill_ids.append(str(result.fill.fill_id))
                event_sequence += 1
                log.append(
                    AccountingEvent(
                        event_sequence,
                        EntityId.deterministic("accounting_event", f"{self.fixture_hash}:{variant}:{index}"),
                        result.fill,
                    )
                )
            at = RecordedAt.from_datetime(at.value.replace(minute=(at.value.minute + 1) % 60))
        replayed = SimulationAccount(Decimal("100000"), account_id=account_id)
        log.replay(replayed, account_id=account_id)
        payload: Any = {
            "fixture_hash": self.fixture_hash,
            "variant": variant,
            "orders": tuple(order_ids),
            "fills": tuple(fill_ids),
            "ledger_cash": str(account.state.cash),
            "replay_cash": str(replayed.state.cash),
            "position_quantity": str(sum((lot.quantity for lot in account.state.lots), Decimal("0"))),
        }
        return L2ReplayResult(
            self.fixture_hash,
            variant,
            tuple(order_ids),
            tuple(fill_ids),
            str(account.state.cash),
            str(replayed.state.cash),
            payload["position_quantity"],
            canonical_sha256(payload),
        )

    def replay_l2_matrix(self) -> L2ReplayMatrix:
        """Run base, counterfactual and execution-cost stress through L2."""
        variants = (
            self.replay_l2(),
            self.replay_l2(variant="counterfactual"),
            self.replay_l2(variant="stress", cost_multiplier=Decimal("2")),
        )
        digest = canonical_sha256(
            {"fixture_hash": self.fixture_hash, "variants": tuple(item.result_hash for item in variants)}
        )
        return L2ReplayMatrix(self.fixture_hash, variants, digest)

    def replay_v1_l2_matrix(self) -> dict[str, object]:
        """Expose the V1 walk-forward/stress/counterfactual funnel and L2 facts.

        V1's fold planner remains the authority for OOS windows; V2's engine
        is the authority for executable order/fill/account facts. Keeping both
        digests in one result makes it impossible to claim a V1 metric was an
        L2 execution result or to silently substitute a different planner.
        """
        matrix = self.replay_l2_matrix()
        return {
            "fixture_hash": self.fixture_hash,
            "walk_forward_manifest": self.manifest(),
            "counterfactual_manifest": self.counterfactual_manifest(),
            "stress_manifest": self.stressed_manifest(),
            "l2_matrix_hash": matrix.matrix_hash,
            "l2_result_hashes": tuple(item.result_hash for item in matrix.variants),
            "deterministic": matrix.deterministic,
        }

    def _variant_manifest(self, signals: tuple[int, ...], variant: str, *, cost: Decimal | None = None) -> str:
        fixture = FrozenStrategySpecFixture(
            f"{self.fixture_id}:{variant}",
            self.version,
            signals,
            self.labels,
            self.forward_returns,
            self.signal_times,
            self.label_times,
            self.per_signal_cost if cost is None else cost,
            self.train_bars,
            self.test_bars,
            self.step_bars,
            self.embargo_bars,
        )
        return fixture.manifest()


def replay_v1_candidate_l2_matrix(candidate: ReplayEpisodeCandidate) -> dict[str, object]:
    """Replay an actual V1 MVP-R candidate through the shared V2 L2 matrix.

    This is the production-shaped bridge used by qualification tests: the
    input is selected by ``mvp_replay.stratified_replay_candidates`` from
    point-in-time dataset records, while order/fill/account facts come solely
    from the V2 simulation engine.
    """
    fixture = FrozenStrategySpecFixture.from_mvp_replay_candidate(candidate)
    result = fixture.replay_v1_l2_matrix()
    result.update(
        {
            "instrument_id": candidate.instrument_id,
            "stratum": candidate.stratum.value,
            "market_cutoff": candidate.market_cutoff.to_dict()["recorded_at"],
            "v1_input_record_count": len(candidate.records),
            "v1_future_record_event_time": candidate.future_record.event_time.to_dict()["recorded_at"],
            "v1_input_sha256": canonical_sha256(
                {
                    "records": tuple(
                        {
                            "event_time": item.event_time.to_dict()["recorded_at"],
                            "available_time": item.available_time.to_dict()["recorded_at"],
                            "values": cast(JsonValue, dict(item.values)),
                        }
                        for item in (*candidate.records, candidate.future_record)
                    )
                }
            ),
        }
    )
    return result


__all__ = [
    "FrozenStrategySpecFixture",
    "L2ReplayResult",
    "L2ReplayMatrix",
    "replay_v1_candidate_l2_matrix",
]
