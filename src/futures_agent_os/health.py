"""Dependency-free process health contract for the greenfield repository."""

from dataclasses import asdict, dataclass
from typing import Final


PROJECT_NAME: Final = "futures-agent-os"


@dataclass(frozen=True, slots=True)
class HealthStatus:
    """Minimal health response shared by local and future service entry points."""

    status: str
    project: str
    version: str
    legacy_runtime_dependency: bool

    def as_dict(self) -> dict[str, str | bool]:
        return asdict(self)


def get_health_status() -> HealthStatus:
    """Return local process health without consulting external systems."""

    return HealthStatus(
        status="ok",
        project=PROJECT_NAME,
        version="0.0.1",
        legacy_runtime_dependency=False,
    )

