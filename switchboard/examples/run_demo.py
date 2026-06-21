"""End-to-end demo of the Switchboard Operator.

Run it with no API key to watch the architecture move (simulated backend):

    python examples/run_demo.py

Set ANTHROPIC_API_KEY (and `pip install claude-agent-sdk`) to run it for real.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from switchboard import CapabilityGraph, Decree, Node, SwitchboardOperator  # noqa: E402


def build_graph() -> CapabilityGraph:
    g = CapabilityGraph()
    # A small "graph spine of dimensions of use": each node is one dimension.
    g.add_node(Node(name="researcher", model="claude-haiku-4-5-20251001", cost=0.4,
                    capabilities="research gather sources find information search facts data"))
    g.add_node(Node(name="writer", model="claude-haiku-4-5-20251001", cost=0.5,
                    capabilities="write draft compose prose summary report narrative text"))
    g.add_node(Node(name="coder", model="claude-haiku-4-5-20251001", cost=0.6,
                    capabilities="code implement function script program build refactor"))
    g.add_node(Node(name="verifier", model="claude-haiku-4-5-20251001", cost=0.3,
                    capabilities="verify check validate test review confirm audit"))
    return g


async def main() -> None:
    graph = build_graph()
    operator = SwitchboardOperator(graph, max_rounds=5)

    decree = Decree(
        goal=(
            "research the market for agent orchestration tools, "
            "write a one-page summary, "
            "and verify every claim has a source"
        ),
        success_condition="summary exists and all claims are sourced",
    )

    print(f"backend: {operator.backend.name}")
    print(f"DECREE: {decree.goal}\n")

    outcome = await operator.run(decree)

    print(f"SUCCESS: {outcome['success']}\n")
    print("sub-goal -> node routing & outcome:")
    for sg in outcome["subgoals"]:
        res = outcome["results"].get(sg.id)
        node = graph.nodes[res.node_id].name if res else "?"
        status = sg.status.value
        conf = f"{res.confidence:.2f}" if res else "-"
        iters = res.iterations if res else "-"
        print(f"  [{status:8}] {node:10} (conf={conf}, iters={iters})  <- {sg.description[:50]}")

    print()
    print(operator.metamap.summary(graph))

    # Write the meta-map graph for visualisation.
    dot_path = Path(__file__).resolve().parent / "metamap.dot"
    dot_path.write_text(operator.metamap.to_dot(graph))
    print(f"\nmeta-map written to {dot_path}  (render: dot -Tsvg {dot_path.name} -o metamap.svg)")


if __name__ == "__main__":
    asyncio.run(main())
