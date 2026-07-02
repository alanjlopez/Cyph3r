# Testing Cyph3r

Four layers, from "no setup at all" to "full agent against a live graph." Each layer
builds on the previous one; stop wherever you have enough confidence.

> Your Neo4j runs on `127.0.0.1` (your machine), so Layers 1–4 must be run locally.

## Layer 0 — Unit tests (no Neo4j, no API key)

In-memory fakes stand in for both Neo4j and the LLM, so this runs anywhere:

```bash
python3 -m venv .venv && source .venv/bin/activate   # macOS/zsh: venv is required
pip install -e ".[dev]"                              # keep the quotes (zsh globs [dev])
pytest
```

Expect `21 passed`. Covers schema introspection + meta-namespace exclusion,
graph-native memory, the agent's self-repair loop and session learning, the improvement
analyzer, the graph snapshot, and the `cyph3r check` connection doctor.

## Layer 1 — Connect to your Neo4j (viewer, no API key)

Proves your `.env` + Neo4j connection works before involving the LLM.

```bash
cp .env.example .env          # set NEO4J_PASSWORD (and NEO4J_URI if not the default)
cyph3r check                  # tests the connection and diagnoses failures
cyph3r view
```

`cyph3r check` reports the Neo4j version, database, and node count on success; on
failure it prints targeted hints (DBMS stopped, wrong credentials, missing database).

- A browser opens at `http://127.0.0.1:8000/graph/view`. An empty graph (or just the
  counts bar) means the connection works.
- Non-browser equivalent:

  ```bash
  curl -s localhost:8000/graph   # → {"nodes":[],"edges":[],"counts":{...},"truncated":false}
  ```

If it errors, the DBMS is likely stopped, the password is wrong, or `NEO4J_DATABASE`
doesn't match an existing database.

## Layer 2 — Chat: build the graph (needs `ANTHROPIC_API_KEY`)

Add your key to `.env`, then:

```bash
cyph3r chat --session demo
```

Try, one at a time:

1. `Create a Person named Alice who KNOWS a Person named Bob` → runs a write, reports counts.
2. `Who does Alice know?` → answers "Bob" (read/traversal).
3. Refresh `cyph3r view` (or `curl /graph`) → you should see `Alice -[:KNOWS]-> Bob`.

**Self-repair:** ask for something against a not-yet-existing label (e.g.
`List all Movie nodes and their directors`) and watch it hit an error and recover within
a couple of steps (the steps are printed).

## Layer 3 — Memory & continuous improvement

- **Memory across sessions:** quit, re-run `cyph3r chat --session demo`, ask
  `What did we create earlier?` → it recalls from graph-native memory.
- **Improvement pass:** create an isolated node (`Create a Person named Zoe`), then:

  ```bash
  cyph3r improve --session demo
  ```

  It should flag Zoe as an orphan, propose/apply a fix, and record an insight.
- **Domain/meta split:** the viewer hides the agent's `:Cyph3r*` memory nodes by default.
  Tick "include memory" (or `curl 'localhost:8000/graph?include_meta=true'`) to see the
  `:Cyph3rSession` / `:Cyph3rMemory` / `:Cyph3rInsight` nodes — proof memory lives in the
  graph.

## Layer 4 — REST API directly

```bash
uvicorn cyph3r.api:app          # http://127.0.0.1:8000
curl -s localhost:8000/chat -H 'content-type: application/json' \
  -d '{"session_id":"demo","message":"How many nodes are in the graph?"}'
curl -s -X POST localhost:8000/improve -H 'content-type: application/json' \
  -d '{"session_id":"demo"}'
curl -s localhost:8000/sessions
```

The viewer and read endpoints (`/graph`, `/graph/view`, `/sessions`) work without an API
key; `/chat` and `/improve` return `503` if no LLM is configured.

## Cross-check in Neo4j

Everything Cyph3r does is real Cypher, so you can verify independently in Neo4j Desktop's
query view or Neo4j Browser:

```cypher
MATCH (n) RETURN n LIMIT 100
MATCH p=()-->() RETURN p LIMIT 100
```
