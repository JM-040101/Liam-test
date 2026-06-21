"""The Blackboard: shared state store.

Classic blackboard-architecture component. Workers write outputs here and get
back a short `ref`. The operator passes refs around instead of content, so its
own context never balloons with payloads. This is the concrete mechanism behind
law #2 (route pointers, not payloads).
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Entry:
    ref: str
    payload: Any
    meta: dict[str, Any] = field(default_factory=dict)


class Blackboard:
    def __init__(self) -> None:
        self._store: dict[str, Entry] = {}
        self._lock = asyncio.Lock()

    async def write(self, payload: Any, meta: dict[str, Any] | None = None) -> str:
        """Store a payload, return a compact reference to it."""
        ref = f"bb_{uuid.uuid4().hex[:8]}"
        async with self._lock:
            self._store[ref] = Entry(ref=ref, payload=payload, meta=meta or {})
        return ref

    async def read(self, ref: str) -> Any:
        async with self._lock:
            entry = self._store.get(ref)
            return entry.payload if entry else None

    async def read_meta(self, ref: str) -> dict[str, Any]:
        async with self._lock:
            entry = self._store.get(ref)
            return dict(entry.meta) if entry else {}

    async def resolve(self, refs: list[str]) -> dict[str, Any]:
        """Bulk-resolve refs -> payloads (used by a worker to load its inputs)."""
        async with self._lock:
            return {r: self._store[r].payload for r in refs if r in self._store}

    def __len__(self) -> int:
        return len(self._store)
