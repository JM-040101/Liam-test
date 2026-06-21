"""Switchboard Operator -- an orchestration prototype.

A "god node" routes declarative decrees across a weighted capability graph to
headless Ralph-loop workers, then meta-maps the whole run. Built on the Claude
Agent SDK; runs offline as a simulation when no API key is present.
"""

from .backend import ClaudeAgentSDKBackend, SimulatedBackend, get_backend
from .blackboard import Blackboard
from .graph import CapabilityGraph, Edge
from .metamap import MetaMap
from .operator import SwitchboardOperator
from .routing import RoutingFunction, RoutingWeights
from .types import Decree, Node, Result, Status, SubGoal
from .worker import RalphWorker

__all__ = [
    "SwitchboardOperator",
    "CapabilityGraph",
    "Edge",
    "Node",
    "Decree",
    "SubGoal",
    "Result",
    "Status",
    "Blackboard",
    "MetaMap",
    "RoutingFunction",
    "RoutingWeights",
    "RalphWorker",
    "get_backend",
    "ClaudeAgentSDKBackend",
    "SimulatedBackend",
]
