---
name: dojo-onboard
description: Onboard the user's existing Python project into Dojo. Reads their code, asks targeted questions about the data + evaluation, scaffolds `.dojo/`, writes `PROGRAM.md` + `SETUP.md` from the dialogue, and drives `dojo domain setup` until the AI-generated `load_data.py` and `evaluate.py` connectors verify cleanly against the user's data. Use when the user wants to set up Dojo on a project that already has data loaders or an evaluation metric — i.e. they're not just trying the framework on a canned sklearn dataset. Trigger phrases: "onboard my project to Dojo", "set up Dojo here", "run /dojo-onboard", "I want to use Dojo on this codebase".
---

# dojo-onboard

The conversational entry point for getting an existing Python project onto Dojo. The Typer `dojo onboard` works fine for fresh sklearn datasets, but for a real codebase the line-by-line CLI prompts are the wrong UI — the user shouldn't have to compress their data-loading and evaluation logic into single-line answers. This skill makes the setup feel like a conversation: read the user's code, ask a few clarifying questions, write the markdown files yourself, and run the framework's existing CLI commands to scaffold + verify + freeze.

The framework stays the integrity layer (freeze gate, contract verification, runner). You are the discovery + UX layer.

## When to use

Use this skill when the user asks to set Dojo up on a project that already has code — data loaders, a model, a metric. They might say:

- "onboard my project to dojo"
- "set up dojo here"
- "/dojo-onboard"
- "I want to track experiments with dojo on this repo"

**Don't use this skill** when:
- The user wants a quick canned demo → tell them to run `dojo onboard --preset california_housing` and stop.
- The user wants scripted / CI setup with no conversational help → tell them about `dojo onboard --non-interactive --name X` (writes default templates, exits cleanly; user then edits + runs `dojo domain setup`) and stop.
- The user just wants to install Dojo → `uv tool install dojoml`, then come back.

## What you're trying to produce

A directory layout that looks like this when you're done:

```
their-project/
├── .dojo/
│   ├── config.yaml
│   ├── domains/<id>/tools/load_data.py     # AI-generated, verified, frozen
│   ├── domains/<id>/tools/evaluate.py      # AI-generated, verified, frozen
│   └── ...
├── PROGRAM.md       # written by you, from the conversation
├── SETUP.md         # written by you, from the conversation
└── (user's existing code, untouched)
```

And the user can immediately run `dojo run` to start an agent.

## Flow

### 1. Detect repo state — don't ask questions you can answer yourself

Before asking the user anything, look around. Run all of these in parallel:

```bash
ls -la .dojo 2>/dev/null
ls PROGRAM.md SETUP.md 2>/dev/null
cat pyproject.toml 2>/dev/null | head -50
ls *.py **/*.py 2>/dev/null | head -30
dojo --version
```

Inspect what comes back:

- **`.dojo/` already exists.** Stop and ask the user: "There's already a `.dojo/` directory here. Want me to start fresh (delete it), or pick up where it left off?" Don't silently clobber existing work.
- **`pyproject.toml` exists.** Note the package name and Python version — you'll use them as defaults.
- **Existing data-loading code.** If you see something like `load_*.py`, `data.py`, `datasets/`, etc., read those files. Same for anything that smells like evaluation — `eval*.py`, `metrics.py`, files mentioning `mean_squared_error`, `accuracy`, etc.
- **No `dojo` command.** Tell the user to run `uv tool install dojoml` first and stop.

The goal is to come into the conversation already knowing the shape of the user's data and how they evaluate. That way your questions are pointed ("I see you load training data from `data/train.parquet` and split it 80/20 — is that the canonical split, or should the framework split it itself?") rather than generic.

### 2. Ask 2–4 targeted questions

You're trying to fill in the gaps in two markdown files:

- **PROGRAM.md** is the agent's steering prompt: what's the research goal, what counts as success, any constraints the agent should respect.
- **SETUP.md** is the contract the framework freezes: where does the data live, what's the target column / label, what's the train/test split, what metric(s) matter.

Examples of good questions (only ask the ones you can't already infer from the code):

- "What's the target you're predicting — column name or function?"
- "Is there a canonical train/test split, or should the framework split it (e.g. 80/20 random with a fixed seed)?"
- "Which metric is the headline — RMSE, MAE, AUC, something custom? Any metrics you also want logged but not optimized?"
- "Anything the agent should *not* do — e.g. external API calls, modifying a specific file, exceeding a runtime budget?"

Resist asking more than four questions in one go. If you need more, follow up after the first round of files exists.

### 3. Scaffold with `dojo onboard --non-interactive`

```bash
dojo onboard \
  --name <slug-of-project-name> \
  --non-interactive
```

This writes `.dojo/config.yaml`, creates the domain + regression task, and scaffolds default `PROGRAM.md` + `SETUP.md` templates. It stops before tool generation — that's deliberate, because you're about to overwrite the templates with content from the conversation.

Today Dojo only supports `regression`. If the user's task is classification or something else, tell them that's not yet supported, offer to set up a regression task that approximates it (e.g. predict probability), and document the mismatch in PROGRAM.md so the framework's authors can see it.

Pick `<slug>` from the project name (kebab-case, no spaces). Confirm it back to the user once before running.

### 4. Write `PROGRAM.md` and `SETUP.md` directly

After `dojo onboard --non-interactive` runs, both files exist as default templates with TODO placeholders. Use your `Write` tool to overwrite them with content built from the conversation. Don't use `dojo onboard`'s interactive prompts and don't use `typer.edit` — you have the user's words; just write them down.

`SETUP.md` is the higher-stakes file because it's what gets read by `dojo domain setup` to generate the `load_data.py` + `evaluate.py` modules. Be specific:

- **Data**: exact file path(s), file format, target column name, any preprocessing the user does today.
- **Split**: how train/test/validation are produced, whether there's a temporal element, the random seed if any.
- **Metric**: exact metric name, the sklearn / scipy function it maps to if applicable, edge cases (e.g. "RMSE on log-transformed target" — say it).

`PROGRAM.md` can be looser — it's the conversational part the agent reads at the start of every run. Include the user's actual goals, not generic boilerplate.

### 5. Run `dojo domain setup` and watch for verification failures

```bash
dojo domain setup
```

This is the slow step. It calls the LLM to generate the connector code, runs it in a subprocess against the user's actual data, and freezes the task. Timeout is 10 minutes by default.

**Exit code 0**: tools verified and frozen. Continue to step 6.

**Exit code 3**: verification failed. The stderr will contain per-tool errors like:

```
load_data: ModuleNotFoundError: No module named 'pyarrow'
evaluate: KeyError: 'price'
```

For each error, decide:

- **Missing module** → suggest the user install it (or run `uv pip install <module>` for them in the workspace venv if they're okay with it). Re-run `dojo domain setup`.
- **Wrong target column / wrong shape / metric mismatch** → the issue is usually that `SETUP.md` was ambiguous. Edit `SETUP.md` to be more specific, then re-run `dojo domain setup`. **The task is not frozen** when verification fails, so you can re-run without `dojo domain unfreeze`.
- **Code-level bug in generated tools** → tell the user, let them inspect, don't silently rewrite the tools yourself. The framework deliberately puts a human-review gate here.

Iterate up to 3–4 times. If verification still fails, stop and tell the user — at that point either `SETUP.md` needs human input or there's a real bug worth filing.

**Exit code 1 with "task is frozen"**: shouldn't happen, but if it does, run `dojo domain unfreeze && dojo domain setup`. This indicates an older `dojo` version; consider upgrading.

### 6. Hand off to `dojo run`

When `dojo domain setup` exits 0, you're done. Tell the user:

```
Setup complete. Try:

    dojo run

The agent will start writing experiments. Stop it with Ctrl+C or
`dojo stop`. Knowledge atoms produced during the run will be in
.dojo/knowledge/. See PROGRAM.md if you want to refine the steering.
```

Don't invoke `dojo run` yourself — it's a long-running interactive command and you'd just be a worse middle layer between the user and the framework.

## What you must not do

- **Don't bypass the freeze gate.** If verification keeps failing, fix `SETUP.md` (and ask the user) — don't run with `--unsafe-skip-verify`.
- **Don't hand-edit the generated `load_data.py` / `evaluate.py`.** They're regenerated from `SETUP.md` on every `dojo domain setup`. Edit the markdown, not the code.
- **Don't invent task types.** Regression is the only frozen contract today.
- **Don't ask the user the four classic line-by-line prompts** (target, success, dataset, evaluate). Compose the markdown files from the conversation as a whole.
- **Don't silently `rm -rf .dojo/`.** Always confirm.

## Recovery hints

- User wants to start over: `rm -rf .dojo && dojo onboard --non-interactive --name <slug>`.
- User wants to change `SETUP.md` after freeze: edit the file, then `dojo domain unfreeze && dojo domain setup` (regenerates and re-freezes).
- User wants to see what's frozen: `dojo domain show`.
- User wants to swap the agent backend: edit `.dojo/config.yaml` (`agent.backend: claude | stub`).

## Optional: Docker sandbox

If the user mentions experiments that risk OOM-ing their machine, or asks for stronger isolation around training scripts, suggest the Docker sandbox. It runs each experiment inside an ephemeral `docker run` with `--memory` and `--cpus` limits — an OOM kills the container, not the host.

Trade-off worth surfacing before they opt in:

- **Pro:** containment. Bad experiments stop being a laptop-stability problem.
- **Con:** first `dojo domain setup` is slow — it pulls the image and builds a Linux-compatible `.venv-docker/` from the workspace's `pyproject.toml` or `requirements.txt`. Subsequent runs are instant.

To enable, edit `.dojo/config.yaml` *before* running `dojo domain setup`:

```yaml
sandbox:
  backend: docker            # default "local"
  image: python:3.11-slim    # default — matches Dojo's minimum supported Python
  memory_limit: 8g           # optional
  cpu_limit: "4"             # optional
  network: bridge            # default — use "none" for strict isolation
```

Then run `dojo domain setup` as usual — the setup step builds `.venv-docker/` for you. Tell the user to add `.venv-docker/` to their `.gitignore`. To force a rebuild later (e.g. after dep changes), delete the directory and re-run `dojo domain setup`.

Pre-flight check before recommending: confirm `docker info` returns exit 0. If Docker isn't running, point them at `LocalSandbox` (the default) and move on — don't try to set up a backend they can't use today.

## Why a skill instead of more CLI flags

Three reasons the conversational form is right for this:

1. The user's data + evaluation are paragraphs of context, not single-line answers. A skill reads paragraphs.
2. Verification failures are iterative — "wrong target column" means edit `SETUP.md` and try again. A skill loops naturally; a Typer prompt doesn't.
3. The user usually already has the answer in their codebase. A skill can read it; a Typer prompt can only ask.

The Typer `dojo onboard` still exists for users who want a canned preset (`dojo onboard --preset california_housing`) or scripted/CI scaffolding (`dojo onboard --non-interactive --name X`, then edit + `dojo domain setup`). This skill is the third path: for everyone with a real project.
