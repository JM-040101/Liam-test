"""Smoke tests -- run with `python tests/test_smoke.py` or `pytest`.

These exercise the offline path (simulated backend) so they need no API key.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from switchboard import (  # noqa: E402
    CapabilityGraph,
    Decree,
    Node,
    RoutingFunction,
    SimulatedBackend,
    Status,
    SwitchboardOperator,
)


def _graph() -> CapabilityGraph:
    g = CapabilityGraph()
    g.add_node(Node(name="researcher", model="m", cost=0.4,
                    capabilities="research gather sources find search facts"))
    g.add_node(Node(name="writer", model="m", cost=0.5,
                    capabilities="write draft compose summary report prose"))
    g.add_node(Node(name="verifier", model="m", cost=0.3,
                    capabilities="verify check validate test review confirm"))
    return g


def test_routing_picks_capability_match():
    g = _graph()
    rf = RoutingFunction()
    sg = list(SwitchboardOperator(g)._heuristic_decompose(
        Decree(goal="write a summary", success_condition="x")
    ))[0]
    route = rf.select(sg, g)
    assert route is not None
    assert route.node.name == "writer"
    print("ok: routing picks capability match")


def test_end_to_end_converges_and_meta_maps():
    g = _graph()
    op = SwitchboardOperator(g, backend=SimulatedBackend(), max_rounds=5)
    decree = Decree(
        goal="research the market, write a summary, and verify the claims",
        success_condition="summary exists and claims are sourced",
    )
    outcome = asyncio.run(op.run(decree))
    assert outcome["success"] is True
    assert all(s.status == Status.VERIFIED for s in outcome["subgoals"])
    # Meta-map recorded routes + traversals, and learned positive edge weights.
    assert op.metamap.total_tokens() > 0
    assert any(e.weight > 0 for e in g.edges.values())
    print("ok: end-to-end converges and meta-maps")


def test_blackboard_refs_not_payloads():
    """Operator should never receive payloads -- results carry refs."""
    g = _graph()
    op = SwitchboardOperator(g, backend=SimulatedBackend(), max_rounds=3)
    outcome = asyncio.run(op.run(Decree(goal="write a summary", success_condition="x")))
    for res in outcome["results"].values():
        assert isinstance(res.content_ref, str) and res.content_ref.startswith("bb_")
    print("ok: workers return refs, not payloads")


if __name__ == "__main__":
    test_routing_picks_capability_match()
    test_end_to_end_converges_and_meta_maps()
    test_blackboard_refs_not_payloads()
    print("\nall smoke tests passed")
