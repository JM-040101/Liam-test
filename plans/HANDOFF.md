# Switchboard Operator — Technical Handoff

This document is the full context for the work in this thread: what was asked,
what was researched, what was built, why it's built that way, and where to take
it next. It is written for an engineer picking this up cold.

---

## 1. Origin & intent

The work started as a research question about how AI agents should interact with
software, then converged on a concrete build: an **orchestration agent** the
requester described in their own terms as —

> "a switchboard operator for routing across a graph spine of dimensions of use…
> the god node of a graph web of utility… combining Ralph-Wiggum-type loops and
> headless mode with reasoning and inference."

We translated that vision into rigorous primitives and shipped a runnable
prototype: the **Switchboard Operator**. The guiding decision was to make every
poetic term map to a real, testable mechanism rather than hand-wave it.

### Term translation (the Rosetta stone for this codebase)

| Requester's term | Implemented as | Precedent |
|---|---|---|
| "decrees vs orders" | `Decree` (declarative desired-state) decomposed into imperative sub-goals | Kubernetes reconciliation |
| "switchboard operator" | `RoutingFunction` — a scoring/matching function | Mixture-of-Experts gate; blackboard *control* component |
| "god node of a graph web of utility" | `SwitchboardOperator` holding the graph + edge weights | Blackboard architecture; orchestrator-workers |
| "graph spine of dimensions of use" | `CapabilityGraph` (nodes = capabilities, weighted edges) | LangGraph state graph; A2A |
| "Ralph Wiggum loops" + "headless mode" | `RalphWorker` — a headless reconciliation loop | Geoffrey Huntley's "Ralph" technique |
| "bandwidth of metadata / info signals" | `Edge.weight` = signal per 1k tokens; `MetaMap` | Anthropic context-engineering; tool-search token reduction |
| "meta mapped and meta analysed" | `MetaMap` trace graph + analysis + DOT export | — |

---

## 2. Research foundation (what the design rests on)

Before building, five parallel research agents produced a cited landscape. The
findings that directly shaped the architecture:

1. **Interface hierarchy.** Structured programmatic access (API/tool/CLI) beats
   screenshot/computer-use when it exists. CLI/code-execution wins on token cost
   and reliability; MCP wins on multi-tool interoperability; computer-use is the
   unreliable universal fallback. → *We route to typed worker nodes, not pixels.*

2. **Bandwidth is the binding constraint.** In Anthropic's multi-agent research
   system, **token usage alone explained ~80% of performance variance**, and the
   multi-agent setup used ~15× the tokens of single-agent. → *Law #2: route refs,
   not payloads; keep the operator's context tiny.*

3. **Auth.** Static API keys are the wrong access model; scoped, short-lived
   OAuth tokens (now required by the MCP spec for remote servers) are the
   baseline, with per-agent identity (SPIFFE/IETF drafts) emerging. → *Documented
   as a hard requirement: each worker gets a scoped credential, never the hub's.*

4. **Harness design (Anthropic "Building Effective Agents").** Start simple; the
   agent loop is gather-context → act → verify → repeat; tool/ACI design is the
   real craft; long-running agents need durable state + a convergence signal.
   Early autonomous loops (AutoGPT/BabyAGI) failed on infinite loops + lost
   state. → *Laws #1, #4, #5; the Blackboard is durable state; workers self-verify.*

5. **Security — the "lethal trifecta" (Simon Willison, Jun 2025).** Any agent
   with private-data access + untrusted-content exposure + external comms can be
   made to exfiltrate, regardless of model. → *A broad-authority god node is a
   trifecta amplifier; hence the scoped-credential rule.*

> Sourcing caveat carried over from the research: several primary domains
> (anthropic.com, openai.com docs, some vendor blogs) returned HTTP 403 to the
> fetcher, so a few quantitative figures came via search-engine excerpts. The
> MCP spec, arXiv papers, and Anthropic engineering posts are the firm primaries.

### Terminology answer (recorded for completeness)

There is **no single canonical buzzword** for "the moment an AI does a human
action." Precise terms: **"computer use"** (Anthropic) / **"computer-using agent
(CUA)"** (OpenAI) for GUI actions; **"action"** / the *Act* step of the
ReAct loop for the generic moment; **"agentic"** for the umbrella concept.

---

## 3. Architecture

```
                    ┌─────────────────────────────┐
   DECREE  ───────► │   SWITCHBOARD OPERATOR       │  god node (reasoning loop, strong model)
  (goal +           │   holds graph + edge weights │  routes REFS, not payloads
   success cond.)   │   routing = match×load×cost  │
                    └──────────┬──────────────────┘
                ┌──────────────┼──────────────┐
                ▼              ▼              ▼
            ┌────────┐    ┌────────┐    ┌────────┐
            │ ralph  │    │ ralph  │    │ ralph  │   headless workers (cheap model)
            │ loop + │    │ loop + │    │ loop + │   while !verified: run; check; persist
            │ verify │    │ verify │    │ verify │
            └───┬────┘    └───┬────┘    └───┬────┘
                └─────────────┼─────────────┘
                         ┌─────────┐        ┌──────────────┐
                         │BLACKBOARD│  ───►  │  META-MAP     │  weighted trace graph
                         │refs+meta │        │ rank / prune  │  feeds weights back to routing
                         └─────────┘        └──────────────┘
```

### Control flow (one `operator.run(decree)` call)

1. **Decompose** — `Decree` → list of `SubGoal`. Uses the LLM if a real backend
   is present (`SUBGOAL: … || CHECK: …` lines); falls back to a deterministic
   clause-splitter offline.
2. **Round loop** (up to `max_rounds`):
   a. Collect `PENDING`/`FAILED` sub-goals.
   b. **Route** each via `RoutingFunction.select` → a `Node`. Increment that
      node's `load` so a busy node is less attractive *within the same round*.
   c. **Dispatch** all routed sub-goals as `RalphWorker.run` coroutines in
      parallel (`asyncio.gather`).
   d. **Meta-analyse**: for each result, decrement load, fold
      `signal = confidence if verified else 0` into the operator→node edge,
      record a `traversal` event, and set the sub-goal status
      (`VERIFIED` / re-`PENDING` for retry / `FAILED` past `retry_cap`).
   e. Break early if all sub-goals are `VERIFIED`.
3. **Return** `{success, subgoals, results, backend}`.

### The five laws (each maps to code)

1. **Routing is a matching function, not a message bus** — `routing.py`.
2. **Bandwidth is binding → route pointers, not payloads** — `blackboard.py`;
   `Result.content_ref`; the operator never holds worker output.
3. **Declarative at the hub, imperative at the leaves** — `Decree` →
   `SubGoal`; the worker turns a sub-goal into concrete iterations.
4. **Every loop needs a convergence signal** — `SubGoal.success_check` +
   `Node.max_iterations` in `worker.py`.
5. **Expensive inference at the hub, brute force at the leaves** —
   `operator_model` (strong) vs `Node.model` (cheap).

---

## 4. Module reference

| File | Responsibility | Key APIs |
|---|---|---|
| `switchboard/types.py` | Plain dataclasses; the ref-not-payload discipline lives in the docstrings | `Decree`, `SubGoal`, `Node`, `Result`, `Status` |
| `switchboard/blackboard.py` | Async shared store; payloads addressed by short ref | `write`, `read`, `resolve`, `read_meta` |
| `switchboard/graph.py` | Capability graph; edges weighted by signal/token | `CapabilityGraph`, `Edge.weight`, `record_traversal`, `dead_edges`, `prior_weight` |
| `switchboard/routing.py` | The switchboard scoring function | `RoutingFunction.score/select`, `RoutingWeights`, `Route` |
| `switchboard/metamap.py` | Trace graph + analysis + export | `MetaMap.record`, `bottlenecks`, `summary`, `to_dot`, `to_json`, `TraceEvent` |
| `switchboard/backend.py` | **Only SDK-aware module**; real vs simulated | `LLMBackend.complete`, `ClaudeAgentSDKBackend`, `SimulatedBackend`, `get_backend` |
| `switchboard/worker.py` | Ralph-loop worker | `RalphWorker.run`, `_read_signal` |
| `switchboard/operator.py` | The god node / control loop | `SwitchboardOperator.run/decompose` |
| `examples/run_demo.py` | End-to-end demo, writes `metamap.dot` | — |
| `tests/test_smoke.py` | Offline tests (routing, e2e convergence, ref discipline) | — |

### Data contracts worth knowing

- **`Result.content_ref`** is always a Blackboard ref (`bb_…`), never inline
  content. Tests enforce this (`test_blackboard_refs_not_payloads`).
- **`Edge.weight`** = `signal / (tokens/1000)`. Zero tokens → weight 0. This is
  the single number the meta-map ranks and routing reads back as a prior.
- **Worker convergence signal**: a worker's final line is parsed for
  `DONE: <conf>` / `CONTINUE: <conf>`. The simulated backend instead emits
  `progress=<x>` and is treated as done at ≥0.99. See `RalphWorker._read_signal`.

---

## 5. The backend abstraction (most important extension seam)

Everything talks to `LLMBackend.complete(prompt, *, model, system, allowed_tools,
max_turns) -> Completion(text, tokens)`. Two implementations:

- **`ClaudeAgentSDKBackend`** — uses the Claude Agent SDK `query()` (stateless,
  ideal for many parallel headless workers). Headless config:
  `permission_mode="dontAsk"`, `allowed_tools=[]` for pure-text workers. Token
  accounting reads `ResultMessage.usage` with a char/4 fallback.
- **`SimulatedBackend`** — deterministic offline stub; lets the loops, routing,
  blackboard, and meta-map all exercise with no API key (used by CI/tests).

`get_backend()` auto-selects: real SDK iff the package is importable **and**
`ANTHROPIC_API_KEY`/`CLAUDE_CODE_OAUTH_TOKEN` is set; otherwise simulated.

> SDK facts were confirmed against the official Python reference
> (`code.claude.com/docs/en/agent-sdk/python`): package `claude-agent-sdk`,
> import `claude_agent_sdk`, `query()` is an async generator yielding
> `AssistantMessage` (with `.content` blocks) and a terminal `ResultMessage`.

---

## 6. How to run

```bash
cd switchboard
python3 examples/run_demo.py      # offline simulation, no key required
python3 tests/test_smoke.py       # smoke tests (also offline)
```

Real workers:

```bash
pip install -r requirements.txt    # claude-agent-sdk
export ANTHROPIC_API_KEY=sk-...    # or CLAUDE_CODE_OAUTH_TOKEN
python3 examples/run_demo.py
```

Visualise the meta-map:

```bash
dot -Tsvg examples/metamap.dot -o metamap.svg
```

**Verified state at handoff:** demo runs green on the simulated backend (3
sub-goals routed to researcher/writer/verifier, `coder` correctly idle, channel
weights learned); all 3 smoke tests pass. The real-SDK path is written against
the confirmed API but has **not** been exercised against a live key in this
environment — that is the first thing to validate (see §8).

---

## 7. Design decisions & rationale

- **Zero required dependencies for the core.** Stdlib only; the SDK is optional.
  This keeps the prototype inspectable and CI-able without secrets.
- **Lexical Jaccard routing, not embeddings.** Deliberate: it runs offline and
  is trivially swappable. Routing quality is *expected* to be the first thing a
  real deployment upgrades.
- **Single-file SDK isolation.** All provider specifics live in `backend.py`, so
  porting to another model/SDK touches one file.
- **Hierarchical by construction.** A worker node can itself wrap a
  `SwitchboardOperator`, which is the intended answer to the god-node bottleneck
  — not yet wired in the demo, but nothing in the types prevents it.
- **Load is per-round, not global.** `Node.load` nudges distribution within a
  dispatch round and is reset as results return; it is not a long-lived queue.

---

## 8. Known limitations & open questions (the real TODO list)

1. **Real-SDK path is untested against a live key.** Validate token accounting
   (`ResultMessage.usage` shape varies across SDK versions) and that
   `permission_mode="dontAsk"` behaves as a pure-text worker. *Highest priority.*
2. **God node is a SPOF / context bottleneck.** Mitigated by ref-routing but not
   eliminated. Implement the hierarchical operator (worker = sub-operator).
3. **Routing is lexical.** Mis-routing is the dominant expected failure. Swap in
   embedding similarity or LLM-choice in `routing.py`; consider a "return to
   operator" escape hatch for a worker that decides it was mis-routed.
4. **No real credential scoping yet.** The security model is documented but not
   enforced; workers currently share process env. Wire per-worker scoped tokens
   before any untrusted-content exposure.
5. **No persistence across process restarts.** The Blackboard is in-memory.
   Anthropic's long-running-agent pattern (progress file + git) is the reference
   if durability is needed.
6. **Convergence signal is self-reported.** A worker claims `DONE`; there's no
   independent verifier node yet. A dedicated verifier in the loop (the research's
   evaluator-optimizer pattern) would harden this.
7. **Cost is unbounded per run.** No global token budget/ceiling on the control
   loop. Add one before running real fan-out.
8. **`metamap.to_dot` is the only visualisation.** A live/streaming view of the
   graph was offered but not built.

---

## 9. Suggested next steps (in order)

1. Run the real-SDK path against a key; fix token accounting if needed (§8.1).
2. Add a global token budget + per-round cap to `SwitchboardOperator` (§8.7).
3. Implement hierarchical operators (worker-as-sub-operator) (§8.2).
4. Upgrade routing to embeddings or LLM-choice + add the escape hatch (§8.3).
5. Add a standalone verifier node and route verification through it (§8.6).
6. Enforce per-worker scoped credentials (§8.4).

---

## 10. Repository facts

- Branch: `claude/ai-agent-software-integration-ximb7c`
- Layout: the prototype is under `switchboard/` (`switchboard/` package,
  `examples/`, `tests/`, `README.md`, `requirements.txt`); this `HANDOFF.md`
  lives in the repo-root `plans/` folder.
- Generated artifacts (`examples/metamap.dot`, `*.svg`, `__pycache__`) are
  git-ignored.
- The repo was otherwise empty (a stub `README.md`) before this work.

---

## Appendix A — Full research summary (the agent↔software landscape)

The build grew out of a broad research turn. §2 kept only the findings that
shaped the code; this appendix preserves the rest so the document is the
complete record. The original question had four parts: (1) is an API key the
best way for an AI to interact with software; (2) how to build a "harness" so an
agent acts as the user; (3) how to adapt existing software for agent use;
(4) what to call the moment an AI performs a human action. Five parallel agents
researched it (Perplexity wasn't available, so this used WebSearch/WebFetch).

### A.1 Interfaces & the API-key question

- **There is a hierarchy, not one winner:** prefer a structured programmatic
  interface (API exposed as a typed tool, or a CLI) when it exists; fall back to
  computer-use/browser automation only for UI-only systems.
- **CLI is strikingly token-efficient.** A cited benchmark found CLI tools used
  ~1.3k–8.8k tokens/task at ~100% reliability vs MCP's ~32k–82k at 72%
  (10×–32× cheaper); the gap is "almost entirely schema" (43 tool defs injected
  per turn, 1–2 used). *Treat exact multiples as indicative — single benchmark.*
- **MCP wraps APIs, it doesn't replace them** — turns N×M integration into N+M;
  worth it when 3+ tools feed one workflow and runtime discovery matters.
  Anthropic's counters to MCP token bloat: the **Tool Search Tool** (~85% context
  reduction) and **code-execution-with-MCP** (tools as a code API).
- **Accessibility tree / semantic DOM beats screenshots** for structured web:
  ~200–400 tokens/page vs 15k+. Microsoft's Playwright MCP drives browsers from
  a11y snapshots rather than vision. Pure-vision still needed for non-semantic UIs.
- **Computer-use is the least reliable paradigm** (OpenAI CUA ~38% OSWorld at
  launch; frontier models ~80s% on web benchmarks) and most exposed to prompt
  injection; vendors warn against it for precision/sensitive tasks.
- **Auth (the literal "API key" question): static API keys are NOT best.** They
  fail on revocability, attribution, scoping, rotation. Baseline = scoped,
  short-lived **OAuth 2.1** tokens (now *required* by the MCP spec for remote
  servers; `client_credentials` for no-human-present calls). Frontier = per-agent
  **verifiable identity** (SPIFFE/SVID, IETF drafts, vendors like Aembit/WorkOS).
  Reality check: a 2026 survey found **93% of agent projects still use unscoped
  API keys** and **74% report over-privileged agents**.

### A.2 Harness architecture

- Agent vs workflow (Anthropic): *workflows* follow predefined code paths;
  *agents* let the LLM direct its own process. Guidance: **start simple**.
- Canonical loop: perceive → reason → act → observe (**ReAct**, Yao et al. 2022);
  Anthropic's coding variant: gather context → act → verify → repeat.
- **Tool/ACI design is the real craft**: namespace tools, return *actionable*
  errors, make tools token-efficient, prefer few consolidated tools.
- **Sandboxing tiers:** microVMs (Firecracker) > gVisor > hardened containers.
  Plain Docker is insufficient (shared kernel; 2025 runc escape CVEs). Add
  network-egress filtering. OWASP Agentic AI Top 10 (Dec 2025) ranks
  "Unexpected Code Execution" top-tier.
- **Context engineering**: smallest high-signal token set; compaction; persist
  state to files+git for long-running agents. **Multi-agent**: token usage
  explained ~80% of performance variance; ~15× the tokens of single-agent.
- **Frameworks:** Claude Agent SDK, OpenAI Agents SDK (Agents/Handoffs/Guardrails
  /Sessions/Tracing), LangGraph (checkpointed state graph, HITL interrupts).
- Cautionary history: AutoGPT/BabyAGI (2023) failed on infinite loops + lost state.

### A.3 Adapting existing software for agents

- **Agent Experience (AX)** — named discipline coined by Netlify's Matt Biilmann
  (early 2025); "the holistic experience AI agents have as the user of a product."
  Four pillars: Access, Context, Tools, Orchestration.
- **`llms.txt` — skip it or treat as low-proof.** Adopted (800k+ sites) but
  Google explicitly doesn't support it and an Ahrefs analysis found ~97% of
  published files got **zero** crawler requests. Prefer real structured data +
  robots.txt + MCP tools.
- **Wrapping REST as MCP is the dominant retrofit** (FastMCP, Azure APIM), **but
  1:1 thin wrapping is an anti-pattern** — an arXiv study of 116 servers found
  92% are bare API wrappers exposing ~19% of operations. APIs are *resource*-based;
  good agent tools are *task*-based (orchestrate several calls into one intent).
- **Design endpoints for agents:** idempotency keys (agents retry ~15–30% of
  calls), machine-readable errors (RFC 7807), strong typed schemas, small
  deterministic steps.
- **Reuse the accessibility tree** — broken a11y breaks agents like it breaks
  screen readers, making the investment dual-purpose.

### A.4 Standards & frameworks landscape

- **MCP** (Anthropic, Nov 2024). Architecture: JSON-RPC clients↔servers exposing
  tools/resources/prompts (LSP-inspired). Current spec **2025-11-25** (added
  Tasks); 2025-03-26 added Streamable HTTP + OAuth 2.1; 2025-06-18 made servers
  OAuth Resource Servers + Elicitation. Adopted by OpenAI (Mar 2025), Google
  (Apr 2025). **Donated to the Agentic AI Foundation (Linux Foundation) Dec 9,
  2025**; ~97M monthly SDK downloads, ~10k servers at the one-year mark.
- **A2A** (Google, Apr 2025) — agent↔agent discovery/delegation; donated to Linux
  Foundation Jun 2025; 150+ orgs. Complementary to MCP, not competing.
- **Computer use:** Anthropic public beta Oct 2024 (Claude 3.5 Sonnet,
  screenshot-action loop); OpenAI Operator/CUA Jan 2025 → folded into "ChatGPT
  agent" Jul 2025. Function calling underpins all of it.

### A.5 Terminology — "the moment an AI does a human action"

**No single canonical buzzword exists** (be skeptical of "agentic moment" etc.).
Best-fit terms: **"computer use" / "computer-using agent (CUA)"** for GUI
clicking/typing; **"action" / the Act step** of the ReAct loop for the generic
moment; **"agentic"** for the umbrella (2025 word of the year). Adjacent:
*tool use/function calling*, *GUI grounding* (locating the element), *HITL vs
human-on-the-loop*, *embodiment* (physical/robotic only), and the *RPA* lineage
(rule-based bots; agentic AI is the reasoning successor).

### A.6 Cross-cutting: security

- **Lethal trifecta** (Simon Willison, Jun 2025): private-data access + untrusted
  content + external comms ⇒ exfiltration risk, regardless of model.
- **Meta's "Agents Rule of Two"** (Oct 2025): hold at most two of those three.
- **MCP tool-poisoning** produced real 2025 CVEs (MCPoison CVE-2025-54136,
  CurXecute CVE-2025-54135).

> Sourcing caveat: several primaries (anthropic.com, openai.com docs, some vendor
> blogs) returned HTTP 403; some quantitative figures came via search excerpts.
> MCP spec, arXiv papers, and Anthropic engineering posts are the firm primaries.

---

## Appendix B — Decision log & thread chronology

1. **Research turn** — broad question on agent↔software interaction; answered via
   a 5-agent parallel research fan-out (the `deep-research` skill, run manually).
2. **Concept turn** — requester reframed toward an orchestration agent
   ("switchboard operator / god node / Ralph loops / graph spine"). We produced a
   first-principles synthesis (the five laws) and the term-translation table.
3. **Substrate decision** — offered four build substrates; requester chose the
   **Claude Agent SDK** (over pure bash+`claude -p`, LangGraph, or a design doc).
4. **Build** — Python, stdlib-only core, offline-first via a simulated backend,
   all SDK specifics isolated to `backend.py`. Demo + smoke tests green offline.
5. **Handoff** — this document.

Key standing choices: Python; zero-dependency core; lexical routing (swappable);
single-file SDK isolation; hierarchical-ready operator. Open decisions are the
§8 limitations — the most important being validating the real-SDK path.
