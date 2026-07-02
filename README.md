# Cyph3r

[![CI](https://github.com/alanjlopez/Cyph3r/actions/workflows/ci.yml/badge.svg)](https://github.com/alanjlopez/Cyph3r/actions/workflows/ci.yml)

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
  snapshot.py   point-in-time nodes/edges view for visualization
  web.py        the interactive vis-network viewer page
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

### Connecting to a local Neo4j Desktop instance

If you run Neo4j locally with **Neo4j Desktop** instead of Docker, point Cyph3r at it via
`.env` — no code changes needed:

1. **Start the DBMS.** In Neo4j Desktop, start your instance (it must be *running*, not
   stopped). Note its **Connection URI** (e.g. `neo4j://127.0.0.1:7687`).
2. **Make sure a database exists.** Once started, the default database is usually named
   `neo4j`. If the Databases list is empty, click **Create database** and note the name.
3. **Set `.env`** to match (the URI scheme may be `neo4j://` or `bolt://` — both work for a
   single local instance):

   ```ini
   NEO4J_URI=neo4j://127.0.0.1:7687
   NEO4J_USER=neo4j
   NEO4J_PASSWORD=<the password you set in Neo4j Desktop>
   NEO4J_DATABASE=neo4j      # or the database name you created
   ```

4. **Verify the connection without an API key:** run `cyph3r check`. It tests the
   connection and prints a diagnosis with fix hints (DBMS stopped, wrong password,
   missing database). Once it reports `Connected`, use `cyph3r view` to see the graph,
   then add `ANTHROPIC_API_KEY` and use `cyph3r chat` to start building it.

> The DBMS folder path and ID shown in Neo4j Desktop are not needed — Cyph3r connects
> over Bolt using only the Connection URI, user, password, and database name.

## Usage

```bash
# Interactive chat (resume a named session)
cyph3r chat --session demo

# Run a continuous-improvement pass
cyph3r improve --session demo

# See the graph: launches a server and opens an interactive view in your browser.
# Works without an LLM API key — only a Neo4j connection is needed.
cyph3r view                     # then explore at http://127.0.0.1:8000/graph/view

# REST API
uvicorn cyph3r.api:app
curl -s localhost:8000/chat -H 'content-type: application/json' \
  -d '{"session_id":"demo","message":"How many nodes are in the graph?"}'
```

### Viewing the graph

- `cyph3r view` (or `GET /graph/view`) renders the live graph with vis-network: pan/zoom,
  click a node to see its properties, adjust the node limit, and reload on demand.
- `GET /graph?limit=300&include_meta=false` returns the raw snapshot as JSON
  (`nodes`, `edges`, `counts`, `truncated`). The whole graph is shown up to `limit`
  nodes; a banner appears when the view is truncated.
- By default the agent's own memory (`:Cyph3r*` nodes) is hidden; pass `include_meta=true`
  (or tick "include memory" in the viewer) to show it.
- The viewer and all read endpoints work even without `ANTHROPIC_API_KEY`; only `/chat`
  and `/improve` require the LLM (they return 503 otherwise).

## Testing

```bash
pytest
```

The unit tests use in-memory fakes for both Neo4j and the LLM, so they run without a
live database or API key. They cover schema introspection + meta-namespace exclusion,
graph-native memory, the agent's self-repair loop and session learning, and the
improvement analyzer.

For end-to-end testing against a live Neo4j (viewer, chat, memory, improvement, and the
REST API), see **[TESTING.md](TESTING.md)** — a layered walkthrough from unit tests to
the full agent.
