# 🥋 Dojo — An AI-powered autonomous ML research platform.

<div align="center">
  <img src="assets/dojo-logo-no-bg.png" alt="Dojo.ml logo" width="200" />

  <p><strong>Define a research domain. Agents run many experiments, build a compressed knowledge base, and surface what actually works.</strong></p>
</div>

---

<div align="center">
  <img src="assets/dojo_chat_example.png" alt="Dojo chat example" width="800" />
</div>

---

## What is Dojo?

You define the **domain** — a research area with goals, data, and tools. AI agents handle the rest: planning hypotheses, writing and executing experiment code, logging metrics, and continuously distilling findings into a growing knowledge base.

```
Domain (you define)
  └── Experiments (agent creates — many per domain)
        └── Knowledge Atoms (produced, linked, versioned, compressed)
```

Every insight is linked back to the experiments that produced it. Knowledge compounds over time instead of getting lost in logs.

---

## Current Status

> **⚠️ Proof of Concept** — Dojo is under active development. The following constraints apply:

**Now**
- **Agent**: Claude Code only (via `claude` CLI subprocess)
- **Compute**: Local only (in-process / subprocess)
- **Storage**: Local only (JSON files on disk)

**Future**
- **Agents**: Multiple SDK backends — Claude, GitHub Copilot, ChatGPT
- **Compute**: Sandboxed cloud execution via [Modal](https://modal.com)
- **Storage**: Persistent cloud storage via [Supabase](https://supabase.com)

---

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)
- [just](https://github.com/casey/just)
- Node.js 18+ (frontend)

## Quick Start

```bash
# 1. Install all dependencies
just dev

# 2. Run with stub agent (no API key needed — great for exploring)
just run-stub

# 3. Run with Claude agent (uses your Claude Code CLI subscription)
just run-claude
```

Backend → `http://localhost:8000` · Frontend → `http://localhost:5173`

## Claude Authentication

Dojo uses the `claude` CLI as a subprocess — it inherits whatever account you're already logged into. **No API key needed** for regular agent runs if you have Claude Code installed.

`ANTHROPIC_API_KEY` is only required for AI-assisted domain tool generation (`POST /domains/{id}/generate-tools`).

---

## Config

Create `.dojo/config.yaml` in your project root:

```yaml
agent:
  backend: stub        # "stub" (no LLM) or "claude"
tracking:
  backend: file        # "file" or "mlflow"
```

Or use environment variables:

```bash
DOJO_AGENT__BACKEND=claude
DOJO_TRACKING__BACKEND=mlflow
```

---

## Tests

```bash
just test       # all tests
just lint       # ruff check
just format     # auto-fix lint + format
```

---

## Project Structure

```
src/dojo/
  core/         # Domain models, Experiment, KnowledgeAtom, state machine
  agents/       # AgentBackend ABC + Claude / Stub backends
  api/          # FastAPI app + routers (/domains, /experiments, /knowledge, /agent)
  tools/        # Agent tools (experiments, knowledge, tracking)
  runtime/      # LabEnvironment (DI container), ExperimentService, KnowledgeLinker
  storage/      # Local JSON adapters (domain, experiment, knowledge)
  tracking/     # FileTracker, MlflowTracker
  config/       # pydantic-settings + YAML config
frontend/       # React 19 + Vite 7 + shadcn/ui dark theme
tests/          # unit, integration, e2e
```

---

## Key API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/domains` | Create a research domain |
| `POST` | `/agent/run` | Start an agent run on a domain |
| `GET` | `/agent/runs/{id}/events` | Live SSE event stream |
| `GET` | `/experiments?domain_id=` | List experiments |
| `GET` | `/knowledge?domain_id=` | List knowledge atoms |
| `GET` | `/health` | Health check |

See [AGENTS.md](AGENTS.md) for the full API reference and architecture details.
