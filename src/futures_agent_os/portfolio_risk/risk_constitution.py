"""Deterministic sizing and Risk Constitution checks for simulation plans."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from futures_agent_os.decision import RiskDecision, RiskDecisionOutcome, TradePlan
from futures_agent_os.shared_kernel import EntityId, RecordedAt


class RiskRuleCode(StrEnum):
    """Stable machine-readable rule outcomes emitted by ``RiskEngine``.

    Codes are deliberately kept independent from explanatory text.  A code
    is stable across evaluations while the Constitution ``version`` identifies
    the rule set that produced it.
    """

    KILL_SWITCH = "KILL_SWITCH"
    DATA_QUALITY_UNAVAILABLE = "DATA_QUALITY_UNAVAILABLE"
    DATA_QUALITY_INSUFFICIENT = "DATA_QUALITY_INSUFFICIENT"
    CONCENTRATION_UNAVAILABLE = "CONCENTRATION_UNAVAILABLE"
    CONCENTRATION_LIMIT = "CONCENTRATION_LIMIT"
    INSTRUMENT_CONCENTRATION_UNAVAILABLE = "INSTRUMENT_CONCENTRATION_UNAVAILABLE"
    INSTRUMENT_CONCENTRATION_LIMIT = "INSTRUMENT_CONCENTRATION_LIMIT"
    DIRECTION_CONCENTRATION_UNAVAILABLE = "DIRECTION_CONCENTRATION_UNAVAILABLE"
    DIRECTION_CONCENTRATION_LIMIT = "DIRECTION_CONCENTRATION_LIMIT"
    PORTFOLIO_CONCENTRATION_UNAVAILABLE = "PORTFOLIO_CONCENTRATION_UNAVAILABLE"
    PORTFOLIO_CONCENTRATION_LIMIT = "PORTFOLIO_CONCENTRATION_LIMIT"
    DAILY_DRAWDOWN_UNAVAILABLE = "DAILY_DRAWDOWN_UNAVAILABLE"
    DAILY_DRAWDOWN_LIMIT = "DAILY_DRAWDOWN_LIMIT"
    MARGIN_HEADROOM_UNAVAILABLE = "MARGIN_HEADROOM_UNAVAILABLE"
    MARGIN_BUFFER_LIMIT = "MARGIN_BUFFER_LIMIT"
    DELIVERY_HORIZON_UNAVAILABLE = "DELIVERY_HORIZON_UNAVAILABLE"
    DELIVERY_TOO_NEAR = "DELIVERY_TOO_NEAR"
    RISK_NOT_COMPUTABLE = "RISK_NOT_COMPUTABLE"
    MAX_SINGLE_LOSS = "MAX_SINGLE_LOSS"
    MAX_MARGIN = "MAX_MARGIN"
    RISK_WITHIN_LIMITS = "RISK_WITHIN_LIMITS"


@dataclass(frozen=True, slots=True)
class RiskConstitution:
    ref: str
    version: int
    content_hash: str
    max_single_loss: Decimal
    max_margin: Decimal
    max_quantity: Decimal
    margin_rate: Decimal
    max_concentration: Decimal | None = None
    kill_switch: bool = False
    min_data_quality: Decimal = Decimal("0")
    delivery_horizon_days: int | None = None
    # Optional dimension-specific concentration ceilings.  The original
    # ``max_concentration`` remains a compatibility aggregate ceiling.
    max_instrument_concentration: Decimal | None = None
    max_direction_concentration: Decimal | None = None
    max_portfolio_concentration: Decimal | None = None
    # ``margin_buffer`` accepts either a ratio in [0, 1) or an absolute
    # currency amount.  ``margin_buffer_ratio`` is an explicit alias for
    # callers that do not want the dual-unit compatibility behaviour.
    margin_buffer: Decimal = Decimal("0")
    margin_buffer_ratio: Decimal | None = None
    max_daily_drawdown: Decimal | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.ref, str) or not self.ref.strip() or any(c.isspace() for c in self.ref):
            raise ValueError("constitution ref must be canonical")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ValueError("constitution version must be positive")
        if (
            not isinstance(self.content_hash, str)
            or len(self.content_hash) != 64
            or any(character not in "0123456789abcdef" for character in self.content_hash)
        ):
            raise ValueError("constitution hash must be SHA-256")
        for value in (self.max_single_loss, self.max_margin, self.max_quantity, self.margin_rate):
            if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
                raise ValueError("constitution limits must be positive finite decimals")
        if self.max_concentration is not None and (
            not isinstance(self.max_concentration, Decimal)
            or not self.max_concentration.is_finite()
            or self.max_concentration <= 0
        ):
            raise ValueError("max_concentration must be positive when provided")
        for optional_value, label in (
            (self.max_instrument_concentration, "max_instrument_concentration"),
            (self.max_direction_concentration, "max_direction_concentration"),
            (self.max_portfolio_concentration, "max_portfolio_concentration"),
            (self.max_daily_drawdown, "max_daily_drawdown"),
        ):
            if optional_value is not None and (
                not isinstance(optional_value, Decimal) or not optional_value.is_finite() or optional_value <= 0
            ):
                raise ValueError(f"{label} must be positive when provided")
        if (
            not isinstance(self.margin_buffer, Decimal)
            or not self.margin_buffer.is_finite()
            or self.margin_buffer < 0
            or self.margin_buffer > self.max_margin
        ):
            raise ValueError("margin_buffer must be a finite non-negative amount within max_margin")
        if self.margin_buffer_ratio is not None and (
            not isinstance(self.margin_buffer_ratio, Decimal)
            or not self.margin_buffer_ratio.is_finite()
            or not 0 <= self.margin_buffer_ratio < 1
        ):
            raise ValueError("margin_buffer_ratio must be a finite Decimal in [0, 1)")
        if self.margin_buffer and self.margin_buffer_ratio is not None:
            raise ValueError("specify margin_buffer or margin_buffer_ratio, not both")
        if (
            not isinstance(self.kill_switch, bool)
            or not isinstance(self.min_data_quality, Decimal)
            or not self.min_data_quality.is_finite()
            or not 0 <= self.min_data_quality <= 1
        ):
            raise ValueError("invalid risk quality settings")
        if self.delivery_horizon_days is not None and (
            isinstance(self.delivery_horizon_days, bool)
            or not isinstance(self.delivery_horizon_days, int)
            or self.delivery_horizon_days < 0
        ):
            raise ValueError("delivery horizon must be non-negative")


class RiskEngine:
    def __init__(self, constitution: RiskConstitution) -> None:
        self.constitution = constitution

    def size(self, plan: TradePlan) -> Decimal:
        distance = abs(plan.entry_price - plan.protection.stop_price)
        if distance <= 0:
            raise ValueError("risk is not computable")
        quantity = min(plan.quantity, self.constitution.max_single_loss / distance)
        if quantity <= 0:
            raise ValueError("risk size is zero")
        return min(quantity, self.constitution.max_quantity)

    def decide(
        self,
        plan: TradePlan,
        *,
        decision_id: EntityId,
        now: RecordedAt,
        data_quality: Decimal | None = None,
        concentration: Decimal | None = None,
        days_to_delivery: int | None = None,
        instrument_concentration: Decimal | None = None,
        direction_concentration: Decimal | None = None,
        portfolio_concentration: Decimal | None = None,
        daily_drawdown: Decimal | None = None,
        current_margin: Decimal | None = None,
        margin_used: Decimal | None = None,
        daily_loss: Decimal | None = None,
        instrument_exposure: Decimal | None = None,
        direction_exposure: Decimal | None = None,
        portfolio_exposure: Decimal | None = None,
    ) -> RiskDecision:
        # These aliases make the boundary explicit for callers that expose
        # account facts as ``*_used``/``*_exposure`` while retaining the
        # concise names used by the original V2 slice.
        if margin_used is not None:
            if current_margin is not None and current_margin != margin_used:
                return self._reject(plan, decision_id, now, RiskRuleCode.RISK_NOT_COMPUTABLE)
            current_margin = margin_used
        if daily_loss is not None:
            if daily_drawdown is not None and daily_drawdown != daily_loss:
                return self._reject(plan, decision_id, now, RiskRuleCode.RISK_NOT_COMPUTABLE)
            daily_drawdown = daily_loss
        for primary, alias in (
            (instrument_concentration, instrument_exposure),
            (direction_concentration, direction_exposure),
            (portfolio_concentration, portfolio_exposure),
        ):
            if primary is not None and alias is not None and primary != alias:
                return self._reject(plan, decision_id, now, RiskRuleCode.RISK_NOT_COMPUTABLE)
        instrument_concentration = (
            instrument_concentration if instrument_concentration is not None else instrument_exposure
        )
        direction_concentration = direction_concentration if direction_concentration is not None else direction_exposure
        portfolio_concentration = portfolio_concentration if portfolio_concentration is not None else portfolio_exposure
        if self.constitution.kill_switch:
            return self._reject(plan, decision_id, now, RiskRuleCode.KILL_SWITCH)
        if data_quality is not None and (
            not isinstance(data_quality, Decimal) or not data_quality.is_finite() or not 0 <= data_quality <= 1
        ):
            return self._reject(plan, decision_id, now, RiskRuleCode.DATA_QUALITY_UNAVAILABLE)
        if concentration is not None and (
            not isinstance(concentration, Decimal) or not concentration.is_finite() or concentration < 0
        ):
            return self._reject(plan, decision_id, now, RiskRuleCode.CONCENTRATION_UNAVAILABLE)
        if days_to_delivery is not None and (
            isinstance(days_to_delivery, bool) or not isinstance(days_to_delivery, int) or days_to_delivery < 0
        ):
            return self._reject(plan, decision_id, now, RiskRuleCode.DELIVERY_HORIZON_UNAVAILABLE)
        for value in (
            instrument_concentration,
            direction_concentration,
            portfolio_concentration,
            daily_drawdown,
            current_margin,
        ):
            if value is not None and (not isinstance(value, Decimal) or not value.is_finite() or value < 0):
                return self._reject(plan, decision_id, now, RiskRuleCode.RISK_NOT_COMPUTABLE)
        if self.constitution.min_data_quality > 0 and data_quality is None:
            return self._reject(plan, decision_id, now, RiskRuleCode.DATA_QUALITY_UNAVAILABLE)
        if data_quality is not None and data_quality < self.constitution.min_data_quality:
            return self._reject(plan, decision_id, now, RiskRuleCode.DATA_QUALITY_INSUFFICIENT)
        if self.constitution.max_concentration is not None and concentration is None:
            return self._reject(plan, decision_id, now, RiskRuleCode.CONCENTRATION_UNAVAILABLE)
        if (
            self.constitution.max_concentration is not None
            and concentration is not None
            and concentration > self.constitution.max_concentration
        ):
            return self._reject(plan, decision_id, now, RiskRuleCode.CONCENTRATION_LIMIT)
        dimension_checks = (
            (
                self.constitution.max_instrument_concentration,
                instrument_concentration,
                RiskRuleCode.INSTRUMENT_CONCENTRATION_UNAVAILABLE,
                RiskRuleCode.INSTRUMENT_CONCENTRATION_LIMIT,
            ),
            (
                self.constitution.max_direction_concentration,
                direction_concentration,
                RiskRuleCode.DIRECTION_CONCENTRATION_UNAVAILABLE,
                RiskRuleCode.DIRECTION_CONCENTRATION_LIMIT,
            ),
            (
                self.constitution.max_portfolio_concentration,
                portfolio_concentration,
                RiskRuleCode.PORTFOLIO_CONCENTRATION_UNAVAILABLE,
                RiskRuleCode.PORTFOLIO_CONCENTRATION_LIMIT,
            ),
        )
        for ceiling, observed, unavailable, exceeded in dimension_checks:
            if ceiling is not None and observed is None:
                return self._reject(plan, decision_id, now, unavailable)
            if ceiling is not None and observed is not None and observed > ceiling:
                return self._reject(plan, decision_id, now, exceeded)
        if self.constitution.max_daily_drawdown is not None and daily_drawdown is None:
            return self._reject(plan, decision_id, now, RiskRuleCode.DAILY_DRAWDOWN_UNAVAILABLE)
        if (
            self.constitution.max_daily_drawdown is not None
            and daily_drawdown is not None
            and daily_drawdown > self.constitution.max_daily_drawdown
        ):
            return self._reject(plan, decision_id, now, RiskRuleCode.DAILY_DRAWDOWN_LIMIT)
        if self.constitution.delivery_horizon_days is not None and days_to_delivery is None:
            return self._reject(plan, decision_id, now, RiskRuleCode.DELIVERY_HORIZON_UNAVAILABLE)
        if (
            self.constitution.delivery_horizon_days is not None
            and days_to_delivery is not None
            and days_to_delivery <= self.constitution.delivery_horizon_days
        ):
            return self._reject(plan, decision_id, now, RiskRuleCode.DELIVERY_TOO_NEAR)
        try:
            quantity = self.size(plan)
        except ValueError:
            return RiskDecision(
                decision_id,
                plan.plan_id,
                plan.version,
                RiskDecisionOutcome.REJECT,
                Decimal("0"),
                Decimal("0"),
                Decimal("0"),
                (RiskRuleCode.RISK_NOT_COMPUTABLE,),
                self.constitution.ref,
                now,
                plan.plan_hash,
                risk_constitution_version=self.constitution.version,
                risk_constitution_hash=self.constitution.content_hash,
            )
        loss = abs(plan.entry_price - plan.protection.stop_price) * quantity
        margin = plan.entry_price * quantity * self.constitution.margin_rate
        if loss > self.constitution.max_single_loss:
            return RiskDecision(
                decision_id,
                plan.plan_id,
                plan.version,
                RiskDecisionOutcome.REJECT,
                Decimal("0"),
                loss,
                margin,
                (RiskRuleCode.MAX_SINGLE_LOSS,),
                self.constitution.ref,
                now,
                plan.plan_hash,
                risk_constitution_version=self.constitution.version,
                risk_constitution_hash=self.constitution.content_hash,
            )
        margin_buffer_enabled = self.constitution.margin_buffer > 0 or (
            self.constitution.margin_buffer_ratio is not None and self.constitution.margin_buffer_ratio > 0
        )
        if margin_buffer_enabled and current_margin is None:
            return self._reject(plan, decision_id, now, RiskRuleCode.MARGIN_HEADROOM_UNAVAILABLE)
        if self.constitution.margin_buffer_ratio is not None:
            buffer_amount = self.constitution.max_margin * self.constitution.margin_buffer_ratio
        elif self.constitution.margin_buffer < 1:
            # Preserve the initial V2 slice's ratio interpretation for values
            # such as .20, while allowing an absolute amount >= 1.
            buffer_amount = self.constitution.max_margin * self.constitution.margin_buffer
        else:
            buffer_amount = self.constitution.margin_buffer
        effective_margin_limit = self.constitution.max_margin - buffer_amount
        if margin + (current_margin or Decimal("0")) > effective_margin_limit:
            return RiskDecision(
                decision_id,
                plan.plan_id,
                plan.version,
                RiskDecisionOutcome.REJECT,
                Decimal("0"),
                loss,
                margin,
                (RiskRuleCode.MARGIN_BUFFER_LIMIT if buffer_amount > 0 else RiskRuleCode.MAX_MARGIN,),
                self.constitution.ref,
                now,
                plan.plan_hash,
                risk_constitution_version=self.constitution.version,
                risk_constitution_hash=self.constitution.content_hash,
            )
        outcome = RiskDecisionOutcome.APPROVE if quantity == plan.quantity else RiskDecisionOutcome.MODIFY
        return RiskDecision(
            decision_id,
            plan.plan_id,
            plan.version,
            outcome,
            quantity,
            loss,
            margin,
            (RiskRuleCode.RISK_WITHIN_LIMITS,),
            self.constitution.ref,
            now,
            plan.plan_hash,
            risk_constitution_version=self.constitution.version,
            risk_constitution_hash=self.constitution.content_hash,
        )

    def _reject(self, plan: TradePlan, decision_id: EntityId, now: RecordedAt, code: str) -> RiskDecision:
        return RiskDecision(
            decision_id,
            plan.plan_id,
            plan.version,
            RiskDecisionOutcome.REJECT,
            Decimal("0"),
            Decimal("0"),
            Decimal("0"),
            (code,),
            self.constitution.ref,
            now,
            plan.plan_hash,
            risk_constitution_version=self.constitution.version,
            risk_constitution_hash=self.constitution.content_hash,
        )
