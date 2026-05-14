# 🥋 Dojo — An AI-powered autonomous ML research framework.

<div align="center">
  <img src="assets/dojo-logo-no-bg.png" alt="Dojo.ml logo" width="200" />

  <p><strong>Run controlled, reproducible ML experiments on your existing pipelines and build a memory of what actually works.</strong></p>
</div>

---

<div align="center">
  <video src="https://github.com/user-attachments/assets/c0ff01d5-2c2d-408f-a2fd-22cc6d400e2c" alt="Dojo test example" width="800" controls></video>
</div>

---

## What is Dojo?

You define a **domain** — a research area pointing at your data with a fixed evaluation contract. An AI agent runs experiments inside that contract: writing training code, calling frozen `load_data` and `evaluate` tools, logging metrics, and recording findings as durable knowledge atoms.

The agent owns the training code. The framework owns evaluation. That separation is what makes the metrics trustworthy run-over-run, and what makes it safe to leave the agent unsupervised.

## What's a domain?

A **domain** is a frozen research contract: one `load_data` + one `evaluate` + one workspace. Many experiments live inside it.

- **Create a new domain** when the **data source, target variable, or evaluation metric changes**.
- **Don't** create a new domain when you want to try a new model, hyperparameter, or feature — that's an experiment, and experiments are the agent's job.

> **⚠️ Proof of Concept** — under active development. Single-tenant, local-first, open source. Today only `RegressionTask` is supported; more task types are coming once regression is solid.

---

## Quickstart — recommended path

The recommended way to onboard a real project is the **`dojo-onboard` Claude Code skill**. It reads your code, asks a few targeted questions about the data + evaluation, writes `PROGRAM.md` + `SETUP.md` from the conversation, and drives the framework to generate + verify + freeze the contract.

```bash
uv tool install dojoml              # one-time
dojo skill install dojo-onboard     # one-time, requires Claude Code
cd path/to/your/python/project
claude                              # in Claude Code, run: /dojo-onboard
dojo run                            # after the skill finishes
```

Prerequisites:
- Python 3.11+
- [Claude Code](https://claude.com/claude-code) installed (for the skill path)
- The `claude` CLI logged in — Dojo shells out to it for agent runs (no `ANTHROPIC_API_KEY` needed)
- (Optional) Docker, if you want experiments to run inside a containerised sandbox — see [Run experiments inside Docker](#run-experiments-inside-docker)

## Fallback — `dojo onboard` (no Claude Code)

If you don't have Claude Code, the built-in Typer wizard does the same setup interactively:

```bash
uv tool install dojoml
cd path/to/your/python/project
dojo onboard                        # interactive prompts
dojo run
```

For scripted / CI use, `dojo onboard --non-interactive --name my-project` writes default `PROGRAM.md` + `SETUP.md` templates and stops; edit the files, then run `dojo domain setup`.

## Try a preset (tire-kicker)

To see Dojo work end-to-end on a canned dataset with no existing project:

```bash
mkdir housing && cd housing
dojo onboard --preset california_housing
dojo run --max-turns 30
```

## Configuration

`.dojo/config.yaml` in your project root:

```yaml
agent:
  backend: claude      # "stub" (no LLM, deterministic) or "claude"
tracking:
  backend: file        # "file" or "mlflow"
```

Env-var overrides use **double underscore** for nested fields: `DOJO_AGENT__BACKEND=stub`, `DOJO_TRACKING__BACKEND=mlflow`.

## Run experiments inside Docker

By default, the agent's experiment scripts run in a host subprocess (`LocalSandbox`). For runaway training jobs that might OOM your laptop, opt into the containerised sandbox so each script runs inside an ephemeral `docker run` with `--memory` and `--cpus` limits — an OOM kills the container, not the host.

```yaml
# .dojo/config.yaml
sandbox:
  backend: docker           # default "local"
  image: python:3.11-slim   # default — matches Dojo's minimum supported Python
  memory_limit: 8g          # optional; passed to `docker --memory`
  cpu_limit: "4"            # optional; passed to `docker --cpus`
  network: bridge           # default — set "none" for strict isolation
```

Or via env vars: `DOJO_SANDBOX__BACKEND=docker DOJO_SANDBOX__MEMORY_LIMIT=8g`.

When docker is selected, `dojo domain setup` builds a sibling `.venv-docker/` next to your host `.venv/` from your `pyproject.toml` or `requirements.txt`, so macOS users don't have to manage a Linux-compatible venv by hand. **First setup pulls the image + installs deps (can take minutes); subsequent runs are instant.** Add `.venv-docker/` to your `.gitignore`. Delete the directory and re-run `dojo domain setup` to force a rebuild after dep changes.

Caveats: `python:3.11-slim` doesn't ship build tools — if your deps need native compilation (e.g. `psycopg2` from source), point `sandbox.image` at a beefier image or one you've baked the deps into. `OOMKilled` (exit 137) and `exec format error` (exit 126) responses are tagged with a `[dojo]` marker in stderr explaining the fix.

## Pointers

- [CLAUDE.md](CLAUDE.md) — architecture, directory map, conventions, recipes.
- [docs/ARTIFACTS.md](docs/ARTIFACTS.md) — per-run artifacts and how tracking forwards them.
- [docs/HTTP_API.md](docs/HTTP_API.md) — HTTP API surface (also discoverable at `/docs` when `dojo start` is running).
- [docs/MASTER_PLAN.md](docs/MASTER_PLAN.md) — vision and design.
- [docs/RELEASING.md](docs/RELEASING.md) — release flow.

## Development

Clone, then:

```bash
just dev                           # install backend (uv sync) + frontend (npm install)
just test                          # pytest -v
just lint                          # ruff check + format check
```

Full server + web UI dev loop: `just run-stub` (or `just run-claude`). Backend at `http://localhost:8000`, frontend at `http://localhost:5173`. The React frontend is **not bundled in the PyPI release yet** — run it from a checkout.
