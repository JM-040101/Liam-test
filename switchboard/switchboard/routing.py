"""The routing function -- the heart of the switchboard.

Routing is a *matching* function, not a message bus (law #1). For each sub-goal
we score every candidate node on three axes and pick the best:

    score = w_match * capability_match
          - w_load  * load_penalty
          - w_cost  * cost_penalty
          + w_prior * learned_channel_weight   (from the meta-map)

`capability_match` is a deliberately simple lexical overlap so the prototype
runs offline with zero API calls. Swap it for embedding similarity (or let the
operator LLM choose) without touching the rest of the system.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .graph import CapabilityGraph
from .types import Node, SubGoal

_WORD = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def _overlap(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)  # Jaccard


@dataclass
class RoutingWeights:
    match: float = 1.0
    load: float = 0.15
    cost: float = 0.10
    prior: float = 0.25


@dataclass
class Route:
    node: Node
    score: float
    breakdown: dict[str, float]


class RoutingFunction:
    def __init__(self, weights: RoutingWeights | None = None) -> None:
        self.w = weights or RoutingWeights()

    def score(self, subgoal: SubGoal, node: Node, graph: CapabilityGraph) -> Route:
        match = _overlap(subgoal.description, node.capabilities)
        load_penalty = float(node.load)
        cost_penalty = node.cost
        prior = graph.prior_weight("operator", node.id)

        s = (
            self.w.match * match
            - self.w.load * load_penalty
            - self.w.cost * cost_penalty
            + self.w.prior * prior
        )
        return Route(
            node=node,
            score=s,
            breakdown={
                "match": round(match, 3),
                "load_penalty": round(load_penalty, 3),
                "cost_penalty": round(cost_penalty, 3),
                "prior": round(prior, 3),
            },
        )

    def select(self, subgoal: SubGoal, graph: CapabilityGraph) -> Route | None:
        """Pick the highest-scoring node. Returns None if the graph is empty."""
        routes = [self.score(subgoal, n, graph) for n in graph.nodes.values()]
        if not routes:
            return None
        return max(routes, key=lambda r: r.score)
