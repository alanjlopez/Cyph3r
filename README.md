# Cyph3r

A self-improving LLM agent that **reads, traverses, creates, and modifies a Neo4j
graph** through Cypher. It is one step beyond an MCP server: instead of only exposing
Cypher tools to some external host, Cyph3r owns the agent loop — it introspects the live
schema, plans multi-step operations, traverses the graph, writes and self-repairs
Cypher, **remembers what it learns inside the graph itself**, and **continuously
improves the graph** over time.

## What it does

- **Schema-aware generation + self-repair** — injects the live domain schema into the
  prompt; when a query errors, the error is fed back to the model, which corrects and
  retries (bounded).
- **Multi-step planning + traversal** — first-class `traverse` (N-hop expansion) and
  `find_path` (shortest path) tools alongside raw read/write Cypher and an idempotent
  `create_relationship`.
- **Graph-native memory** — sessions, conversation history, and durable learnings live
  in Neo4j as nodes in a reserved namespace (`Cyph3rSession` / `Cyph3rMessage` /
  `Cyph3rMemory` / `Cyph3rInsight`), with memories linked to the domain entities they
  concern via `:ABOUT`. The domain graph and this meta graph never mix.
- **Continuous improvement** — `analyze_graph` finds orphans and duplicate candidates;
  the agent proposes and **auto-applies** fixes in write transactions (rolled back on
  error) and records what it changed as an insight.

## Architecture

```
cyph3r/
  config.py     settings (.env)
  graph.py      Neo4jClient + GraphClient protocol
  schema.py     live-schema introspection + cached model
  memory.py     graph-native memory (the :Cyph3r* subgraph)
  traversal.py  neighbours / paths / relationship creation
  improve.py    analyze() + fix helpers
  llm/          provider-agnostic interface + Anthropic reference impl
  tools.py      the tool surface exposed to the LLM
  agent.py      the control loop (self-repair, memory, learning)
  factory.py    assemble an agent from settings
  cli.py        chat REPL + improve command
  api.py        FastAPI app
```

The LLM is behind an `LLMProvider` interface (`llm/base.py`); the reference
implementation is Anthropic Claude (`claude-opus-4-8`, adaptive thinking). Other
providers slot in by implementing the same interface.

## Setup

```bash
pip install -e .[dev]
cp .env.example .env   # then fill in NEO4J_PASSWORD and ANTHROPIC_API_KEY

# A local Neo4j for development:
docker run -p7474:7474 -p7687:7687 -e NEO4J_AUTH=neo4j/testpassword neo4j:5
```

## Usage

```bash
# Interactive chat (resume a named session)
cyph3r chat --session demo

# Run a continuous-improvement pass
cyph3r improve --session demo

# REST API
uvicorn cyph3r.api:app
curl -s localhost:8000/chat -H 'content-type: application/json' \
  -d '{"session_id":"demo","message":"How many nodes are in the graph?"}'
```

## Testing

```bash
pytest
```

The unit tests use in-memory fakes for both Neo4j and the LLM, so they run without a
live database or API key. They cover schema introspection + meta-namespace exclusion,
graph-native memory, the agent's self-repair loop and session learning, and the
improvement analyzer.
