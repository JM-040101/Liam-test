"""The Switchboard Operator -- the god node.

Responsibilities, and nothing more (keeping it thin is what lets it scale):
  1. Turn a DECREE into SUB-GOALS (declarative -> routable units).
  2. ROUTE each sub-goal to a node via the routing function.
  3. DISPATCH headless Ralph-loop workers in parallel.
  4. META-ANALYSE results: update edge weights, record the meta-map, re-route
     failures (capped), and check the decree's global success condition.

It reads only metadata + refs back from workers (law #2). For a deeper tree,
a worker node could itself be another Operator -- the design is hierarchical by
construction, which is how you avoid one omniscient bottleneck.
"""

from __future__ import annotations

import asyncio
import re

from .backend import LLMBackend, get_backend
from .blackboard import Blackboard
from .graph import CapabilityGraph
from .metamap import MetaMap, TraceEvent
from .routing import RoutingFunction
from .types import Decree, Result, Status, SubGoal
from .worker import RalphWorker

_CLAUSE_SPLIT = re.compile(r"\s*(?:;|,| and | then |\.)\s*")


class SwitchboardOperator:
    def __init__(
        self,
        graph: CapabilityGraph,
        *,
        backend: LLMBackend | None = None,
        operator_model: str = "claude-opus-4-8",
        max_rounds: int = 5,
        retry_cap: int = 2,
    ) -> None:
        self.graph = graph
        self.backend = backend or get_backend()
        self.operator_model = operator_model
        self.max_rounds = max_rounds
        self.retry_cap = retry_cap

        self.bb = Blackboard()
        self.routing = RoutingFunction()
        self.metamap = MetaMap()

    # -- decomposition: decree -> sub-goals -----------------------------------

    async def decompose(self, decree: Decree) -> list[SubGoal]:
        if self.backend.name != "simulated":
            try:
                return await self._llm_decompose(decree)
            except Exception:
                pass  # fall back to heuristic
        return self._heuristic_decompose(decree)

    async def _llm_decompose(self, decree: Decree) -> list[SubGoal]:
        prompt = (
            f"DECREE (desired end-state): {decree.goal}\n"
            f"GLOBAL SUCCESS CONDITION: {decree.success_condition}\n\n"
            "Break this into 2-5 independent sub-goals that can run in parallel. "
            "Output one per line, exactly: 'SUBGOAL: <desc> || CHECK: <how to verify>'"
        )
        completion = await self.backend.complete(
            prompt, model=self.operator_model, system="You are a planning operator."
        )
        subs: list[SubGoal] = []
        for line in completion.text.splitlines():
            if "SUBGOAL:" in line and "CHECK:" in line:
                desc = line.split("SUBGOAL:", 1)[1].split("||")[0].strip()
                check = line.split("CHECK:", 1)[1].strip()
                subs.append(SubGoal(description=desc, success_check=check, decree_id=decree.id))
        self.metamap.record(
            TraceEvent(kind="decompose", src="operator", dst="operator",
                       tokens=completion.tokens, detail={"n": len(subs)})
        )
        return subs or self._heuristic_decompose(decree)

    def _heuristic_decompose(self, decree: Decree) -> list[SubGoal]:
        clauses = [c.strip() for c in _CLAUSE_SPLIT.split(decree.goal) if len(c.strip()) > 3]
        clauses = clauses or [decree.goal]
        return [
            SubGoal(description=c, success_check=decree.success_condition, decree_id=decree.id)
            for c in clauses
        ]

    # -- the control loop -----------------------------------------------------

    async def run(self, decree: Decree) -> dict:
        subgoals = await self.decompose(decree)
        results: dict[str, Result] = {}

        for round_no in range(1, self.max_rounds + 1):
            pending = [s for s in subgoals if s.status in (Status.PENDING, Status.FAILED)]
            if not pending:
                break

            # Route + dispatch this round's pending sub-goals in parallel.
            dispatched: list[tuple[SubGoal, RalphWorker]] = []
            for sg in pending:
                route = self.routing.select(sg, self.graph)
                if route is None:
                    continue
                node = route.node
                node.load += 1  # load-aware: discourage piling onto one node this round
                sg.status = Status.ROUTED
                sg.attempts += 1
                self.metamap.record(
                    TraceEvent(kind="route", src="operator", dst=node.id,
                               detail={"score": round(route.score, 3), **route.breakdown,
                                       "subgoal": sg.description[:60]})
                )
                dispatched.append((sg, RalphWorker(node, self.backend, self.bb)))

            round_results = await asyncio.gather(*(w.run(sg) for sg, w in dispatched))

            # Meta-analyse: fold results back into edge weights + statuses.
            for (sg, _), res in zip(dispatched, round_results):
                node = self.graph.nodes[res.node_id]
                node.load = max(0, node.load - 1)
                signal = res.confidence if res.verified else 0.0
                self.graph.record_traversal("operator", node.id, res.tokens_used, signal)
                self.metamap.record(
                    TraceEvent(kind="traversal", src="operator", dst=node.id,
                               tokens=res.tokens_used, signal=signal,
                               detail={"verified": res.verified, "iters": res.iterations})
                )
                results[sg.id] = res
                if res.verified:
                    sg.status = Status.VERIFIED
                elif sg.attempts > self.retry_cap:
                    sg.status = Status.FAILED  # give up; stays failed, loop will exit
                else:
                    sg.status = Status.PENDING  # re-route next round

            if all(s.status == Status.VERIFIED for s in subgoals):
                self.metamap.record(
                    TraceEvent(kind="converge", src="operator", dst="operator",
                               detail={"round": round_no})
                )
                break

        success = all(s.status == Status.VERIFIED for s in subgoals)
        return {
            "decree": decree,
            "success": success,
            "subgoals": subgoals,
            "results": results,
            "backend": self.backend.name,
        }
