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

```
Domain (you define)
  ├── Task            — the contract: load_data + evaluate (frozen, AI-generated at setup)
  ├── Workspace       — your repo / pipeline (local path or git url)
  └── Experiments     — agent-created, many per domain
        └── Knowledge atoms — linked across experiments, accumulating over time
```

The agent owns the training code. The framework owns evaluation. That separation is what makes the metrics trustworthy run-over-run, and what makes it safe to leave the agent unsupervised.

Inspired by [Karpathy's autoresearch](https://github.com/karpathy/autoresearch) — `prepare.py` is frozen, `train.py` is fair game, `program.md` is what the human iterates on. Dojo generalises that pattern to any well-defined ML problem class.

---

## Status

> **⚠️ Proof of Concept** — under active development. Open source. Single-tenant, local-first, by design.

- **Agent**: Claude Agent SDK (uses your local `claude` CLI auth — no API key needed for runs)
- **Storage**: Local JSON files in `.dojo/` — your data stays on your machine
- **Tasks supported**: `RegressionTask` (more types to come once regression is solid)

---

## Install

The package on PyPI is [`dojoml`](https://pypi.org/project/dojoml/); the CLI binary it installs is `dojo`.

```bash
uv tool install dojoml         # recommended — isolated, on your PATH
# or
pipx install dojoml
# or
pip install dojoml
```

**Prerequisites:**

- Python 3.13+
- The `claude` CLI logged in ([Claude Code](https://docs.claude.com/claude-code)) — Dojo shells out to it; no `ANTHROPIC_API_KEY` needed for agent runs.

---

## Quickstart — `dojo onboard`

`dojo onboard` is the recommended entry point. Run it inside an existing
Python project — it adds `.dojo/` next to your code, reuses your
`pyproject.toml` / `requirements.txt` for dependencies, and walks you
through everything else:

```bash
cd path/to/your/python/project
uv tool install dojoml          # one-time
dojo onboard                    # answers a few questions, generates load_data + evaluate, freezes the task
dojo run                        # the agent starts running experiments
```

That's it. Your research lives at `.dojo/` in the project (knowledge,
runs, frozen tools), and your code stays where it always was. `dojo onboard`
asks for:

- the agent + tracking + linker backends (sensible defaults — hit enter)
- a domain name + description
- how to fill in `PROGRAM.md` + `SETUP.md` — **open them in `$EDITOR` now** (recommended for short content) or **skip and finish manually** (writes default templates, stops before tool generation so you can edit at your own pace and run `dojo task setup` when ready)

When you pick "open in `$EDITOR`", onboard then runs the AI tool generator,
verifies `load_data` + `evaluate` against the frozen regression contract,
and freezes the task. If the verifier hits a missing import, onboard
offers to install it into the workspace venv and retries automatically.

When you pick "skip", onboard stops cleanly after writing the templates.
Edit `PROGRAM.md` + `SETUP.md`, then run `dojo task setup` to generate +
verify + freeze when you're ready.

### Existing codebase? Use the `dojo-onboard` Claude Code skill

For real projects — where you already have data loaders, a metric, and
paragraphs of context — the Typer prompts are the wrong UI. We ship a
**Claude Code skill** that runs the whole flow as a conversation: it
reads your code, asks a few targeted questions, drafts `PROGRAM.md` +
`SETUP.md` from your answers, drives `dojo task setup`, and iterates on
verifier failures until the AI-written `load_data.py` + `evaluate.py`
connectors verify cleanly against your data.

```bash
uv tool install dojoml      # if you haven't already
dojo skill install dojo-onboard
# then in Claude Code, from your project directory:
/dojo-onboard
```

`dojo skill install` fetches the skill from this repo into
`~/.claude/skills/dojo-onboard/`. Pass `--scope project` to install into
`./.claude/skills/` for the current project only, or `--ref main` to
pull the latest from `main` instead of the installed version's tag.
The skill requires [Claude Code](https://claude.com/claude-code)
installed locally — it's not invoked by `dojo` directly.

### Don't have a project yet? Try a preset

If you just want to see Dojo work end-to-end on a canned dataset:

```bash
mkdir housing && cd housing
dojo onboard --preset california_housing   # ready-to-run PROGRAM.md + SETUP.md
dojo run --max-turns 30
```

The `california_housing` preset uses `sklearn.datasets.fetch_california_housing`
and pre-installs `scikit-learn`, `pandas`, `numpy`, `matplotlib` into a
fresh venv. More presets coming.

### Scripted setup (`dojo init`)

For CI or non-interactive use where prompts aren't acceptable, the older
four-step path is still available:

```bash
dojo init --name housing --task-type regression --non-interactive
$EDITOR PROGRAM.md SETUP.md
dojo task setup
dojo run
```

> **If the AI keeps generating the wrong adapters** on real-world
> pipelines (unusual pandas multi-indexes, custom dataset APIs, wrapping
> an existing evaluator), set Opus 4.7 as the tool-generation model:
>
> ```bash
> DOJO_AGENT__TOOL_GENERATION_MODEL=claude-opus-4-7 dojo task setup
> ```
>
> Opus is slower (~30–60s vs 15–30s) but noticeably better at translating
> a messy `SETUP.md` into correct `load_data` / `evaluate` modules. Set it
> permanently in `.dojo/config.yaml` under `agent.tool_generation_model`.

What happens under the hood:

- **`dojo onboard` / `dojo init`** writes `.dojo/config.yaml`, creates the domain + regression task with `expected_metrics = [rmse, r2, mae]`, scaffolds `PROGRAM.md` and `SETUP.md`, and sets `current_domain_id`.
- **`dojo task setup`** reads `SETUP.md`, asks the AI to generate `load_data` + `evaluate`, runs each tool in a sandbox against its `ToolContract`, and freezes the task. Verification failures tell you which tool failed and why — fix `SETUP.md` (or the tool code) and re-run. (`dojo onboard` runs this automatically as its last step.)
- **`dojo run`** starts the agent in-process. The agent writes training code; `load_data` and `evaluate` stay frozen. The metric dict from `evaluate` is the only source of truth — `complete_experiment` rejects metric keys outside the contract, so the agent can't smuggle in custom numbers.

Useful neighbours:

```bash
dojo task show               # current task status, tools, frozen?
dojo runs ls                 # recent runs
dojo runs show               # last run's events + cost
dojo program show            # print the live PROGRAM.md
dojo domain use <name>       # switch active domain
```

### Stopping a run

`dojo run` blocks the foreground until the agent finishes. To stop it early:

- **Ctrl-C** in the running terminal — the canonical path. The orchestrator is
  interrupted, the framework asks the backend to summarise any durable
  findings as knowledge atoms (a small one-shot LLM call), then prints a
  final cost line. A second Ctrl-C aborts the cleanup immediately.
- **`dojo stop [run_id]`** from another terminal — marks the run `STOPPED`
  on disk. This does *not* halt an in-process foreground run (the orchestrator
  lives inside the other terminal's Python process); use it to recover
  records left `RUNNING` after a hard kill, or to stop server-mode runs.

### Reviewing what happened

```bash
dojo experiments ls          # rank experiments by the primary metric (best first)
dojo experiments best        # show the single best experiment so far
dojo experiments show <id>   # full detail: hypothesis, metrics, code path, errors
dojo runs show               # last run's events + total cost
```

`dojo experiments ls` orders by the task's `primary_metric` and `direction`
(e.g. `rmse` minimised), so the leader sits on top regardless of run order.
The agent's training code is preserved per-experiment in the workspace as
`__dojo_train_<experiment_id>.py` — `cat` it to reproduce a run by hand.

## Artifacts

Each experiment gets a fresh `.dojo/domains/{id}/runs/{eid}/artifacts/` directory. The runner passes its path as `artifacts_dir` to **both** `train()` and `evaluate()`.

- **`evaluate(..., artifacts_dir)` writes durable per-run diagnostics** — residual plots, calibration curves, error breakdowns. These are produced on every run and are part of the user-defined evaluation contract in `SETUP.md`.
- **`train(..., artifacts_dir)` writes opportunistic artifacts** — model checkpoints (`joblib.dump(model, artifacts_dir / "model.pkl")`), training curves, feature importances. The agent decides when an artifact is worth keeping; not every run will write here.

Everything written to `artifacts_dir` is:

1. Copied into the durable Dojo archive at `.dojo/artifacts/experiments/{eid}/...`.
2. Forwarded to the active tracking backend (`MlflowTracker.log_artifact` uploads to MLflow; `FileTracker` records a reference; `NoopTracker` drops it).

## Configuration

Create `.dojo/config.yaml` in your project root:

```yaml
agent:
  backend: claude      # "stub" (no LLM, deterministic) or "claude"
tracking:
  backend: file        # "file" or "mlflow"
```

Or override via environment variables (note the **double underscore** for nested fields):

```bash
DOJO_AGENT__BACKEND=claude
DOJO_TRACKING__BACKEND=mlflow
```

## Web UI / HTTP API (optional)

```bash
dojo start                   # FastAPI server on http://localhost:8000
```

The server reads the same `.dojo/` your CLI commands write to, so a CLI-started run is visible to the API and vice versa.

> **Note:** the React frontend is **not bundled in the PyPI release yet**. If you want the web UI, run it from a checkout — see [Development](#development) below.

### Migrating from v0.0.10

If your domain has a v0.0.10 `PROGRAM.md` with mixed Goal/Dataset/Evaluate content:

1. Create `SETUP.md` next to `PROGRAM.md` with the existing `## Dataset` and `## Evaluate` sections.
2. Trim `PROGRAM.md` to `## Goal`, `## Target`, `## Success`, `## Notes`.
3. Run `dojo task setup` again — the regression contract is now v4 (train receives `artifacts_dir`), so any frozen task needs re-verification anyway.

---

## Development

Most of the contributor reference lives in [CLAUDE.md](CLAUDE.md) (architecture, directory map, "how do I add X" recipes, conventions). This section is the minimum to clone and run tests.

**Additional prerequisites for the dev path:**

- [uv](https://docs.astral.sh/uv/)
- [just](https://github.com/casey/just)
- Node.js 18+ (only if you want to run the web UI)

```bash
git clone https://github.com/Garsdal/Dojo.git && cd Dojo
just dev                     # install backend + frontend deps
just test                    # run the test suite
just lint                    # ruff check
just format                  # auto-fix lint + format
```

For the full server + web UI dev loop:

```bash
just run-stub                # API + frontend with the stub agent (no LLM, deterministic)
just run-claude              # API + frontend with the Claude agent
```

Backend → `http://localhost:8000` · Frontend → `http://localhost:5173`.

### Pointers

- [CLAUDE.md](CLAUDE.md) — architecture, directory map, conventions, recipes.
- [docs/MASTER_PLAN.md](docs/MASTER_PLAN.md) — vision and the typed-Task design.
- [docs/RELEASING.md](docs/RELEASING.md) — release flow.

### HTTP API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/domains` | Create a research domain |
| `POST` | `/domains/{id}/task` | Attach a Task (regression today) |
| `POST` | `/domains/{id}/tools/generate` | AI-generate `load_data` / `evaluate` from SETUP.md, verify against contract |
| `POST` | `/domains/{id}/task/freeze` | Freeze the task — gated on every required tool's verification |
| `POST` | `/domains/{id}/workspace/setup` | One-time workspace prep (venv + deps) |
| `POST` | `/agent/run` | Start an agent run on a domain (requires a frozen task) |
| `GET` | `/agent/runs/{id}/events` | Live SSE event stream |
| `GET` | `/experiments?domain_id=` | List experiments |
| `GET` | `/knowledge?domain_id=` | List knowledge atoms |
| `GET` | `/health` | Health check |
