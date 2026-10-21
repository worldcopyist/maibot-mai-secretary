"""Small contract for features registered by the MaiBot plugin entry point."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol


class SecretaryModule(Protocol):
    name: str
    state_keys: frozenset[str]

    def load_state(self, data: dict[str, Any]) -> None: ...

    def dump_state(self, payload: dict[str, Any]) -> None: ...

    def on_config_update(self) -> None: ...

    async def tick(self, now: datetime) -> None: ...
