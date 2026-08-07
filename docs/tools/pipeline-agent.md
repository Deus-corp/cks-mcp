# Pipeline Agent (multi‑agent orchestration)

`cks-pipeline-agent` runs a configurable pipeline of `AgentStep`
implementations coordinated by `CKSAgentOrchestrator` (ADR-007).
Each step writes its result as a knowledge object with provenance
and a semantic edge from the previous step, while the orchestrator
publishes `AgentStepStarted` / `AgentStepCompleted` events.

## Quick start

```bash
CKS_MCP_DB_PATH=~/.cks-mcp/cks_mcp.db cks-pipeline-agent
```

## Built‑in steps

- **`ResearcherStep`** — researches a topic and produces a
  `ResearchFinding` node.
- **`ReviewerStep`** — reviews another step's finding and produces a
  `Review` node (with `reviews` edge). Idempotent by content hash.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `CKS_MCP_DB_PATH` | `~/.cks-mcp/cks_mcp.db` | Shared database path |
| `CKS_PIPELINE_POLL_INTERVAL` | `5` | Outbox poll interval (seconds) |
| `CKS_PIPELINE_MAX_RETRIES` | `5` | Max retries before dead‑lettering |
| `CKS_PIPELINE_RESEARCHER_MAX_TOKENS` | `512` | Token limit for ResearcherStep LLM calls |
| `CKS_PIPELINE_REVIEWER_MAX_TOKENS` | `256` | Token limit for ReviewerStep LLM calls |

## Architecture

The orchestrator runs steps sequentially or concurrently, using the
persistent outbox (`cks_outbox_tasks`) for claiming tasks and the
CRDT layer for knowledge object sharing. Each step is an
`AgentStep` implementation that:
- Checks idempotency via a content hash stored in a `transition_log`.
- Calls an LLM (via the existing `auto`/`ollama`/`anthropic` dispatch).
- Commits its finding/verdict + a semantic edge in one atomic
  `evolve_knowledge` call.

## Extending

Implement the `AgentStep` protocol (`orchestrator.py`) to add
custom steps. Place them in `src/cks_mcp/pipeline/` and register
them in the pipeline configuration.

See [ADR-007 CKSAgentOrchestrator](../adr/ADR-007%20CKSAgentOrchestrator.md)
for the full design rationale.
