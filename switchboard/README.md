# Switchboard Operator

An orchestration prototype: a **"god node"** that routes declarative *decrees*
across a weighted **capability graph** to headless **Ralph-loop workers**, then
**meta-maps** the entire run so the routing learns which channels carry signal.

Built on the **Claude Agent SDK**. Runs **offline as a simulation** when no API
key is present, so you can watch the architecture move with zero setup.

```
                    ┌─────────────────────────────┐
   DECREE  ───────► │   SWITCHBOARD OPERATOR       │  god node (reasoning loop)
  (goal +           │   holds graph + edge weights │  routes REFS, not payloads
   success cond.)   │   routing = match×load×cost  │
                    └──────────┬──────────────────┘
                ┌──────────────┼──────────────┐
                ▼              ▼              ▼
            ┌────────┐    ┌────────┐    ┌────────┐
            │ ralph  │    │ ralph  │    │ ralph  │   headless workers (cheap model)
            │ loop + │    │ loop + │    │ loop + │   while !verified: run; check
            │ verify │    │ verify │    │ verify │
            └───┬────┘    └───┬────┘    └───┬────┘
                └─────────────┼─────────────┘
                         ┌─────────┐        ┌──────────────┐
                         │BLACKBOARD│  ───►  │  META-MAP     │ weighted trace graph
                         │refs+meta │        │ prune / rank  │ feeds weights back
                         └─────────┘        └──────────────┘
```

## Quick start

```bash
python examples/run_demo.py          # offline simulation, no key needed
```

For real workers:

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-...      # or CLAUDE_CODE_OAUTH_TOKEN
python examples/run_demo.py
```

The backend auto-selects: real Claude Agent SDK if it's installed **and** a key
is present, otherwise the deterministic simulation.

## The five first-principles laws it encodes

1. **Routing is a matching function, not a message bus.** `routing.py` scores
   every node on `match × load × cost (+ learned prior)` and picks the best.
2. **Bandwidth is the binding constraint — route pointers, not payloads.** The
   operator passes Blackboard *refs*; workers load inputs and write outputs by
   ref. The operator's context never holds the content.
3. **Declarative at the top, imperative at the leaves.** A `Decree` states a
   desired end-state; workers translate it into concrete orders locally.
4. **Every loop needs a convergence signal or it spins.** Each Ralph worker has
   a `success_check` and an iteration cap; no signal ⇒ it stops, it doesn't
   thrash.
5. **Expensive inference at the hub, brute force at the leaves.** The operator
   reasons on a strong model; workers loop on a cheap one.

## Module map

| File | Role |
|------|------|
| `operator.py` | The god node: decompose → route → dispatch → meta-analyse |
| `worker.py`   | Ralph-loop worker (reconciliation loop, headless) |
| `routing.py`  | The switchboard routing function |
| `graph.py`    | Capability graph; edges weighted by signal-per-token |
| `blackboard.py` | Shared state store; payloads addressed by ref |
| `metamap.py`  | Trace graph + meta-analysis (bottlenecks, prune, DOT export) |
| `backend.py`  | **Only** SDK-aware module; SDK or simulated backend |
| `types.py`    | Decree, SubGoal, Node, Result |

## Known limits (by design, documented not hidden)

- The god node is a single point of failure and a context bottleneck. Mitigated
  by routing refs (small context) and by being **hierarchical-ready**: a worker
  node can itself be a `SwitchboardOperator`.
- Routing uses lexical Jaccard match so it runs offline. Swap in embedding
  similarity or LLM-choice in `routing.py` without touching anything else.
- Multi-agent fan-out costs more tokens; only worth it when work parallelises.
- Each worker should get a **scoped, short-lived** credential, never the
  operator's full authority (a broad-authority hub amplifies prompt-injection
  risk).

## Visualise the meta-map

The demo writes `examples/metamap.dot`:

```bash
dot -Tsvg examples/metamap.dot -o metamap.svg
```
