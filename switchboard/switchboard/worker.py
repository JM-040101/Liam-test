"""The Ralph-loop worker (a leaf node).

A worker is a *reconciliation loop* for cognition: re-run the same task,
re-reading current state each time, until a local verification signal passes or
an iteration cap is hit (law #4: no convergence signal -> no orchestration,
just thrashing). It runs headless on a cheap model -- expensive reasoning lives
at the hub, brute force lives at the leaves (law #5).

Crucially, the worker loads its inputs from the Blackboard by ref and writes its
output back as a ref. The operator never sees the payload.
"""

from __future__ import annotations

from .backend import LLMBackend
from .blackboard import Blackboard
from .types import Node, Result, SubGoal


class RalphWorker:
    def __init__(self, node: Node, backend: LLMBackend, blackboard: Blackboard) -> None:
        self.node = node
        self.backend = backend
        self.bb = blackboard

    async def run(self, subgoal: SubGoal) -> Result:
        inputs = await self.bb.resolve(subgoal.input_refs)
        context_block = "\n".join(f"- {k}: {v}" for k, v in inputs.items()) or "(none)"

        total_tokens = 0
        last_text = ""
        verified = False
        confidence = 0.0
        iterations = 0

        for i in range(1, self.node.max_iterations + 1):
            iterations = i
            prompt = (
                f"TASK: {subgoal.description}\n"
                f"SUCCESS CHECK: {subgoal.success_check}\n"
                f"INPUTS:\n{context_block}\n"
                f"PRIOR ATTEMPT: {last_text or '(first attempt)'}\n\n"
                "Do the next increment of work. Then on the FINAL line output "
                "exactly 'DONE: <0-1 confidence>' if the success check is now met, "
                "otherwise 'CONTINUE: <0-1 confidence>'."
            )
            completion = await self.backend.complete(
                prompt,
                model=self.node.model,
                system=f"You are the '{self.node.name}' worker. {self.node.capabilities}",
                allowed_tools=[],
            )
            total_tokens += completion.tokens
            last_text = completion.text
            verified, confidence = self._read_signal(completion.text, fallback_iter=i)
            if verified:
                break

        content_ref = await self.bb.write(
            last_text,
            meta={"node": self.node.name, "subgoal": subgoal.id, "iterations": iterations},
        )
        return Result(
            subgoal_id=subgoal.id,
            node_id=self.node.id,
            content_ref=content_ref,
            verified=verified,
            confidence=confidence,
            tokens_used=total_tokens,
            iterations=iterations,
            note=last_text[:120],
        )

    @staticmethod
    def _read_signal(text: str, fallback_iter: int) -> tuple[bool, float]:
        """Parse the worker's self-reported convergence signal.

        Robust to the offline stub (which reports a numeric 'progress=')."""
        for line in reversed(text.strip().splitlines()):
            up = line.strip().upper()
            if up.startswith("DONE:"):
                return True, _parse_conf(line, 0.8)
            if up.startswith("CONTINUE:"):
                return False, _parse_conf(line, 0.4)
        # Simulated backend path: treat progress>=0.99 as done.
        if "progress=" in text:
            try:
                prog = float(text.split("progress=")[-1].split()[0])
                return prog >= 0.99, prog
            except ValueError:
                pass
        # No signal at all: fail closed but give up after a couple tries.
        return fallback_iter >= 2, 0.3


def _parse_conf(line: str, default: float) -> float:
    try:
        return max(0.0, min(1.0, float(line.split(":", 1)[1].strip().split()[0])))
    except (IndexError, ValueError):
        return default
