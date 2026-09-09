"""Channel-neutral supervision cards built from referenced deterministic facts."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib

from .contracts import OutboundNotification

_CARD_SEVERITIES = {"INFO", "TRADE", "ACTION_REQUIRED", "RISK", "CRITICAL"}


@dataclass(frozen=True, slots=True)
class SupervisionCard:
    card_id: str
    title: str
    severity: str
    fact_refs: tuple[str, ...]
    action_refs: tuple[str, ...] = ()

    @classmethod
    def trade_lifecycle(
        cls,
        card_id: str,
        *,
        severity: str,
        mandate_ref: str,
        opportunity_ref: str,
        plan_ref: str,
        risk_ref: str,
        execution_ref: str,
        position_ref: str,
        protection_ref: str,
        margin_ref: str,
        worst_loss_ref: str,
        review_ref: str,
        action_refs: tuple[str, ...] = (),
    ) -> "SupervisionCard":
        """Build a lifecycle card with every required deterministic fact."""
        return cls(
            card_id,
            "Trade lifecycle",
            severity,
            (
                mandate_ref,
                opportunity_ref,
                plan_ref,
                risk_ref,
                execution_ref,
                position_ref,
                protection_ref,
                margin_ref,
                worst_loss_ref,
                review_ref,
            ),
            action_refs,
        )

    def __post_init__(self) -> None:
        if not self.card_id or not self.title or not self.fact_refs:
            raise ValueError("supervision card requires title and deterministic fact references")
        if self.severity.upper() not in _CARD_SEVERITIES:
            raise ValueError("unsupported supervision severity")
        if any(not ref.strip() or ":" not in ref for ref in self.fact_refs):
            raise ValueError("fact references must identify deterministic sources")
        if any(not ref.strip() or ":" not in ref for ref in self.action_refs):
            raise ValueError("action references must identify deterministic owner actions")
        if self.severity.upper() == "TRADE" and self.action_refs:
            raise ValueError("TRADE notifications cannot request operator actions")
        object.__setattr__(self, "severity", self.severity.upper())

    def notification(self, *, channel: str, conversation_id: str) -> OutboundNotification:
        text = f"{self.title} | facts: {', '.join(self.fact_refs)}"
        if self.action_refs:
            text += f" | actions: {', '.join(self.action_refs)}"
        return OutboundNotification(channel, conversation_id, self.severity, text, self.card_id, self.render_payload())

    def render_payload(self) -> dict[str, object]:
        """Return a Feishu-card-shaped payload containing references only."""
        elements: list[dict[str, object]] = [{"tag": "markdown", "content": f"Facts: {', '.join(self.fact_refs)}"}]
        if self.action_refs:
            elements.append({"tag": "markdown", "content": f"Actions: {', '.join(self.action_refs)}"})
        return {
            "config": {"wide_screen_mode": True},
            "header": {"template": self.severity.lower(), "title": {"tag": "plain_text", "content": self.title}},
            "elements": elements,
            "card_id": self.card_id,
            "content_digest": self.content_digest,
        }

    def dedupe_key(self) -> str:
        """Stable card identity used by every channel adapter."""
        return self.card_id

    @property
    def content_digest(self) -> str:
        """Content identity for audit correlation, independent of delivery channel."""
        payload = "|".join((self.card_id, self.title, self.severity, *self.fact_refs, "--", *self.action_refs)).encode(
            "utf-8"
        )
        return hashlib.sha256(payload).hexdigest()
