"""Explicit MANUAL_TEST simulation entry boundary."""

from __future__ import annotations

from dataclasses import dataclass

from .autonomy_contracts import ExecutionOrigin


@dataclass(frozen=True, slots=True)
class ManualTestContext:
    actor_ref: str
    environment_policy_ref: str
    approval_basis_id: str
    simulation_only: bool = True

    def __post_init__(self) -> None:
        for value, label in (
            (self.actor_ref, "actor_ref"),
            (self.environment_policy_ref, "environment_policy_ref"),
            (self.approval_basis_id, "approval_basis_id"),
        ):
            if not isinstance(value, str) or not value.strip() or any(c.isspace() for c in value):
                raise ValueError(f"{label} must be canonical text")
        if self.environment_policy_ref != "environment://simulation-only" or not self.simulation_only:
            raise ValueError("MANUAL_TEST requires simulation-only environment")


def require_manual_test(origin: ExecutionOrigin, context: ManualTestContext) -> None:
    if origin is not ExecutionOrigin.MANUAL_TEST:
        raise ValueError("manual entry requires MANUAL_TEST execution origin")
    if not isinstance(context, ManualTestContext):
        raise TypeError("manual entry requires typed context")
