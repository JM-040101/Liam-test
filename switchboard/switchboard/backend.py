"""LLM backend abstraction -- the ONLY SDK-aware module.

Everything else in the system talks to `LLMBackend.complete(...)`. We ship two
implementations:

  * ClaudeAgentSDKBackend -- real, headless, parallel-safe. Uses the Claude
    Agent SDK `query()` (one-off / stateless, ideal for spawning many workers).
  * SimulatedBackend      -- deterministic offline stub so the prototype runs
    with no API key (great for CI and for seeing the architecture move).

`get_backend()` auto-selects: real SDK if it's installed AND an API key is
present, otherwise the simulation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Completion:
    text: str
    tokens: int


class LLMBackend:
    name = "base"

    async def complete(
        self,
        prompt: str,
        *,
        model: str,
        system: str = "",
        allowed_tools: list[str] | None = None,
        max_turns: int = 1,
    ) -> Completion:  # pragma: no cover - interface
        raise NotImplementedError


class ClaudeAgentSDKBackend(LLMBackend):
    name = "claude-agent-sdk"

    async def complete(
        self,
        prompt: str,
        *,
        model: str,
        system: str = "",
        allowed_tools: list[str] | None = None,
        max_turns: int = 1,
    ) -> Completion:
        # Imported lazily so the package imports cleanly without the SDK present.
        from claude_agent_sdk import (  # type: ignore
            AssistantMessage,
            ClaudeAgentOptions,
            ResultMessage,
            query,
        )

        options = ClaudeAgentOptions(
            model=model,
            system_prompt=system or "You are a focused worker. Do exactly the task asked.",
            allowed_tools=allowed_tools or [],
            permission_mode="dontAsk",  # fully non-interactive: no TTY prompts
            max_turns=max_turns,
        )

        parts: list[str] = []
        tokens = 0
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if hasattr(block, "text"):
                        parts.append(block.text)
            elif isinstance(message, ResultMessage):
                # Best-effort token accounting across SDK versions.
                usage = getattr(message, "usage", None)
                if isinstance(usage, dict):
                    tokens = int(usage.get("input_tokens", 0)) + int(
                        usage.get("output_tokens", 0)
                    )
                break

        text = "\n".join(parts).strip()
        if not tokens:  # fallback estimate (~4 chars/token)
            tokens = max(1, (len(prompt) + len(text)) // 4)
        return Completion(text=text, tokens=tokens)


class SimulatedBackend(LLMBackend):
    """Offline stand-in. Echoes structured, deterministic 'work' so the loops,
    routing, blackboard and meta-map all exercise realistically without a key."""

    name = "simulated"

    def __init__(self, seed: int = 0) -> None:
        self._counter = seed

    async def complete(
        self,
        prompt: str,
        *,
        model: str,
        system: str = "",
        allowed_tools: list[str] | None = None,
        max_turns: int = 1,
    ) -> Completion:
        self._counter += 1
        # The stub gets "more done" on later iterations so ralph loops converge.
        progress = min(1.0, 0.4 + 0.3 * self._counter)
        text = (
            f"[simulated:{model}] handled: {prompt.splitlines()[0][:80]} "
            f"| progress={progress:.2f}"
        )
        tokens = max(1, (len(prompt) + len(text)) // 4)
        return Completion(text=text, tokens=tokens)


def get_backend() -> LLMBackend:
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"))
    try:
        import claude_agent_sdk  # noqa: F401

        sdk_present = True
    except Exception:
        sdk_present = False

    if sdk_present and has_key:
        return ClaudeAgentSDKBackend()
    return SimulatedBackend()
