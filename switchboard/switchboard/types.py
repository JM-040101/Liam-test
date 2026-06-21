"""Core data types for the Switchboard Operator.

These are deliberately plain dataclasses. The whole architecture is built on a
single discipline: the operator (the "god node") routes *references* and
*metadata*, never large payloads. Payloads live on the Blackboard and are
addressed by `ref`. Keeping that rule is what keeps the operator's context
small enough to scale (see README, law #2: bandwidth is the binding constraint).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


class Status(str, Enum):
    PENDING = "pending"
    ROUTED = "routed"
    RUNNING = "running"
    VERIFIED = "verified"
    FAILED = "failed"


@dataclass
class Decree:
    """A declarative goal handed to the god node.

    A decree states a desired end-state and a machine-checkable success
    condition -- not a sequence of orders. Workers translate decree -> orders
    locally (law #3: declarative at the top, imperative at the leaves).
    """

    goal: str
    success_condition: str
    id: str = field(default_factory=lambda: _id("decree"))


@dataclass
class SubGoal:
    """A unit of work the operator routes to exactly one node."""

    description: str
    success_check: str
    decree_id: str
    id: str = field(default_factory=lambda: _id("sub"))
    status: Status = Status.PENDING
    # References into the Blackboard this sub-goal depends on (pointers, not payloads).
    input_refs: list[str] = field(default_factory=list)
    attempts: int = 0


@dataclass
class Node:
    """A worker node in the capability graph.

    `capabilities` is free-text used by the routing function to score
    capability-match. `cost` is a relative number (cheap models score lower).
    `load` is mutated at runtime by the operator for load-aware routing.
    """

    name: str
    capabilities: str
    model: str
    cost: float = 1.0
    max_iterations: int = 4
    load: int = 0
    id: str = field(default_factory=lambda: _id("node"))


@dataclass
class Result:
    """What a worker writes back. The operator reads only this metadata;
    the actual output sits on the Blackboard under `content_ref`."""

    subgoal_id: str
    node_id: str
    content_ref: str | None
    verified: bool
    confidence: float
    tokens_used: int
    iterations: int
    note: str = ""
    ts: float = field(default_factory=time.time)
