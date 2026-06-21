"""The graph spine: nodes (capabilities) and weighted edges (information channels).

Edges are weighted by *signal per token* -- the core "bandwidth of metadata"
idea. An edge that carries many tokens but produces little signal has a low
weight and is a candidate for pruning. The operator learns these weights at
runtime and feeds them back into routing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .types import Node


@dataclass
class Edge:
    src: str  # node id (or "operator")
    dst: str  # node id
    tokens: int = 0
    signal: float = 0.0  # accumulated useful-signal (e.g. sum of verified*confidence)
    traversals: int = 0

    @property
    def weight(self) -> float:
        """Signal per 1k tokens. High = a high-value channel."""
        if self.tokens == 0:
            return 0.0
        return self.signal / (self.tokens / 1000.0)


class CapabilityGraph:
    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self.edges: dict[tuple[str, str], Edge] = {}

    def add_node(self, node: Node) -> Node:
        self.nodes[node.id] = node
        return node

    def edge(self, src: str, dst: str) -> Edge:
        key = (src, dst)
        if key not in self.edges:
            self.edges[key] = Edge(src=src, dst=dst)
        return self.edges[key]

    def record_traversal(self, src: str, dst: str, tokens: int, signal: float) -> None:
        e = self.edge(src, dst)
        e.tokens += tokens
        e.signal += signal
        e.traversals += 1

    def prior_weight(self, src: str, dst: str) -> float:
        """Learned weight of a channel, used as a routing prior."""
        key = (src, dst)
        return self.edges[key].weight if key in self.edges else 0.0

    def dead_edges(self, min_traversals: int = 2, weight_threshold: float = 0.01) -> list[Edge]:
        """Edges that have been used but carry almost no signal -> prune candidates."""
        return [
            e
            for e in self.edges.values()
            if e.traversals >= min_traversals and e.weight < weight_threshold
        ]
