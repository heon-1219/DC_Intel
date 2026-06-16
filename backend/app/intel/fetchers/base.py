"""SourceFetcher protocol (market-intel-pipeline.md §3). Each social source implements it and
self-disables (enabled=False) when its credentials are absent, so the orchestrator skips it
gracefully — mirrors the M1/M3 provider degradation pattern."""
from typing import Protocol, runtime_checkable

from app.intel.models import RawIntel


@runtime_checkable
class SourceFetcher(Protocol):
    name: str

    @property
    def enabled(self) -> bool:
        """False when required creds/cookies are missing — the orchestrator skips disabled sources."""
        ...

    async def fetch(self, symbols: list[str]) -> list[RawIntel]:
        """Fetch recent items for the tracked `symbols`. Returns [] when disabled or on a handled
        upstream error (never raises through to the orchestrator)."""
        ...
