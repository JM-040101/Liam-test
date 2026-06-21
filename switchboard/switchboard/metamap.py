"""The meta-map: a trace graph of every routing decision and edge traversal.

This is the artifact behind your "meta-mapped web of utility." Every decision
the operator makes is recorded as a trace event; from those events we build a
weighted graph that can be (a) exported to Graphviz DOT for visualisation,
(b) mined for bottleneck nodes, and (c) used to prune dead channels.

Meta-analysis here closes the loop: routing reads the learned edge weights that
the meta-map accumulates.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any

from .graph import CapabilityGraph


@dataclass
class TraceEvent:
    kind: str  # "route" | "traversal" | "decompose" | "converge"
    src: str
    dst: str
    tokens: int = 0
    signal: float = 0.0
    detail: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)


class MetaMap:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    def record(self, event: TraceEvent) -> None:
        self.events.append(event)

    # -- analysis -------------------------------------------------------------

    def bottlenecks(self) -> dict[str, int]:
        """Nodes ranked by how much traffic terminates at them."""
        counts: dict[str, int] = defaultdict(int)
        for e in self.events:
            if e.kind == "traversal":
                counts[e.dst] += 1
        return dict(sorted(counts.items(), key=lambda kv: kv[1], reverse=True))

    def total_tokens(self) -> int:
        return sum(e.tokens for e in self.events)

    def summary(self, graph: CapabilityGraph) -> str:
        lines = ["=== META-MAP SUMMARY ==="]
        lines.append(f"events: {len(self.events)}   total tokens routed: {self.total_tokens()}")
        lines.append("")
        lines.append("channels (operator -> node), by learned weight (signal/1k tok):")
        ranked = sorted(graph.edges.values(), key=lambda e: e.weight, reverse=True)
        for e in ranked:
            src = "operator" if e.src == "operator" else graph.nodes.get(e.src, e.src)
            dst_name = graph.nodes[e.dst].name if e.dst in graph.nodes else e.dst
            lines.append(
                f"  operator -> {dst_name:<14} weight={e.weight:7.3f}  "
                f"tokens={e.tokens:<7} signal={e.signal:.2f}  traversals={e.traversals}"
            )
        dead = graph.dead_edges()
        if dead:
            lines.append("")
            lines.append("prune candidates (used, near-zero signal):")
            for e in dead:
                dst_name = graph.nodes[e.dst].name if e.dst in graph.nodes else e.dst
                lines.append(f"  operator -> {dst_name}")
        return "\n".join(lines)

    # -- export ---------------------------------------------------------------

    def to_dot(self, graph: CapabilityGraph) -> str:
        """Graphviz DOT. `dot -Tsvg metamap.dot -o metamap.svg` to render."""
        out = ['digraph switchboard {', '  rankdir=LR;', '  node [shape=box, style=rounded];']
        out.append('  operator [shape=doublecircle, label="SWITCHBOARD\\n(god node)"];')
        for n in graph.nodes.values():
            out.append(f'  "{n.id}" [label="{n.name}\\n{n.model}"];')
        for e in graph.edges.values():
            pen = 1.0 + min(e.weight, 5.0)
            out.append(
                f'  "{e.src}" -> "{e.dst}" '
                f'[label="w={e.weight:.2f}\\n{e.tokens}tok", penwidth={pen:.1f}];'
            )
        out.append("}")
        return "\n".join(out)

    def to_json(self) -> str:
        return json.dumps([asdict(e) for e in self.events], indent=2)
