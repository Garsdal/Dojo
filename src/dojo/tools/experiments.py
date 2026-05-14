"""Dojo.ml experiment tools — Phase 4 surface.

The agent's per-experiment surface shrinks to a single tool: ``run_experiment``.
The framework drives the lifecycle (PENDING → RUNNING → COMPLETED/FAILED) and
records metrics from the runner's ``__DOJO_METRICS__`` marker. Read-side tools
(``get_experiment``, ``list_experiments``, ``compare_experiments``) stay so
the agent can inspect history and compare runs.

Removed from the MCP surface:
  - ``create_experiment``
  - ``complete_experiment``
  - ``fail_experiment``
  - ``run_experiment_code``

These transitions still happen — the framework calls ``ExperimentService``
internally inside ``run_experiment``. They're just no longer agent-callable.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dojo.core.experiment import CodeRun, Experiment, ExperimentResult, Hypothesis
from dojo.core.task import TASK_TYPE_REGISTRY
from dojo.runtime.experiment_service import ExperimentService
from dojo.runtime.lab import LabEnvironment
from dojo.runtime.runner import (
    RunnerOutcome,
    format_runner_error,
    parse_runner_stdout,
    render_runner,
)
from dojo.runtime.task_service import TaskService
from dojo.tools.base import ToolDef, ToolResult
from dojo.utils.logging import get_logger

logger = get_logger(__name__)


def create_experiment_tools(lab: LabEnvironment) -> list[ToolDef]:
    """Return the experiment tools exposed to the agent (Phase 4 surface)."""
    service = ExperimentService(lab)
    task_service = TaskService(lab)

    async def run_experiment(args: dict[str, Any]) -> ToolResult:
        """Run a complete train + evaluate experiment in one subprocess.

        The agent submits ``train_code`` (a Python module defining
        ``def train(X_train, y_train, X_test, *, artifacts_dir)``); the
        framework writes it alongside an auto-generated runner stub, executes
        the runner, parses metrics from the stdout marker, and transitions
        the experiment state. Anti-cheating: ``evaluate`` is imported from
        the domain's canonical, frozen path — the agent cannot redefine it.
        """
        domain_id = args["domain_id"]
        hypothesis_text = args["hypothesis"]
        train_code = args["train_code"]
        variables = args.get("variables") or {}

        domain = await lab.domain_store.load(domain_id)
        if domain is None:
            return ToolResult(error=f"Domain {domain_id!r} not found")
        if domain.task is None or not domain.task.frozen:
            return ToolResult(
                error=(
                    f"Domain {domain_id!r} has no frozen task — "
                    "freeze it with `dojo domain setup` before running experiments."
                )
            )
        if domain.workspace is None or not domain.workspace.path:
            return ToolResult(error=f"Domain {domain_id!r} has no workspace configured.")

        # 1. Create + transition the experiment record.
        experiment = Experiment(
            domain_id=domain_id,
            hypothesis=Hypothesis(description=hypothesis_text, variables=variables),
        )
        experiment_id = await service.create(experiment)
        await service.run(experiment_id)
        experiment = await service.get(experiment_id)
        assert experiment is not None
        if experiment.result is None:
            experiment.result = ExperimentResult()

        # 2. Lay out files. Train code + runner stub live under
        #    `.dojo/domains/{id}/runs/{eid}/` so the user's repo stays clean.
        #    The artifact under `experiments/<id>/` remains the canonical
        #    archive — that's the place to inspect exactly what produced a
        #    given metric (e.g. via `dojo` CLI / artifact APIs).
        run_number = 1
        train_module = "__dojo_train"
        train_filename = f"{train_module}.py"
        artifact_filename = f"__dojo_train_{experiment_id}.py"

        workspace_path = Path(domain.workspace.path)
        canonical_dir = task_service.canonical_tools_dir(domain_id)
        runs_dir = task_service.runs_dir(domain_id, experiment_id)
        runs_dir.mkdir(parents=True, exist_ok=True)
        artifacts_dir = runs_dir / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        # 2a. Persist train code as an artifact (provenance).
        artifact_path = f"experiments/{experiment_id}/{artifact_filename}"
        await lab.artifact_store.save(artifact_path, train_code.encode())

        # 2b. Write train + runner into the per-experiment runs dir.
        (runs_dir / train_filename).write_text(train_code)
        spec = TASK_TYPE_REGISTRY[domain.task.type]
        runner_code = render_runner(
            train_module=train_module,
            canonical_dir=str(canonical_dir),
            workspace_dir=str(workspace_path),
            train_dir=str(runs_dir),
            callsite=spec.runner_callsite,
            prelude=spec.runner_prelude,
        )

        # 3. Execute the runner from the runs dir (so its script lands there,
        #    not in the user's workspace). cwd stays the workspace so the
        #    agent's train code can do relative imports / file paths against
        #    the user's repo unchanged.
        ws = domain.workspace
        env_vars = dict(ws.env_vars or {})
        env_vars["DOJO_ARTIFACTS_DIR"] = str(artifacts_dir)
        exec_result = await lab.sandbox.execute(
            runner_code,
            cwd=str(workspace_path),
            python_path=ws.python_path,
            env_vars=env_vars,
            name="__dojo_runner",
            script_dir=str(runs_dir),
        )

        # 4. Record the CodeRun before deciding success/failure so the artifact
        #    trail is complete even when the runner crashes.
        ingested = await _ingest_artifacts(
            lab=lab,
            experiment_id=experiment_id,
            artifacts_dir=artifacts_dir,
        )
        experiment.result.code_runs.append(
            CodeRun(
                run_number=run_number,
                code_path=artifact_path,
                description=hypothesis_text,
                exit_code=exec_result.exit_code,
                duration_ms=exec_result.duration_ms,
                timestamp=datetime.now(UTC),
                artifact_paths=ingested,
            )
        )

        outcome = parse_runner_stdout(exec_result.stdout)
        return await _finalise_experiment(
            service=service,
            experiment=experiment,
            domain_task_config=domain.task.config,
            outcome=outcome,
            exec_result=exec_result,
            run_number=run_number,
        )

    async def get_experiment(args: dict[str, Any]) -> ToolResult:
        exp = await service.get(args["experiment_id"])
        if exp is None:
            return ToolResult(error="Not found")
        return ToolResult(
            data={
                "id": exp.id,
                "domain_id": exp.domain_id,
                "state": exp.state.value,
                "hypothesis": exp.hypothesis.description if exp.hypothesis else None,
                "variables": exp.hypothesis.variables if exp.hypothesis else {},
                "config": exp.config,
                "metrics": exp.result.metrics if exp.result else None,
                "logs": exp.result.logs if exp.result else [],
                "error": exp.result.error if exp.result else None,
            }
        )

    async def list_experiments(args: dict[str, Any]) -> ToolResult:
        experiments = await service.list(domain_id=args.get("domain_id"))
        return ToolResult(
            data=[
                {
                    "id": e.id,
                    "state": e.state.value,
                    "hypothesis": e.hypothesis.description if e.hypothesis else None,
                    "metrics": e.result.metrics if e.result else None,
                }
                for e in experiments
            ]
        )

    async def compare_experiments(args: dict[str, Any]) -> ToolResult:
        rows = []
        for eid in args["experiment_ids"]:
            exp = await service.get(eid)
            if exp:
                rows.append(
                    {
                        "id": exp.id,
                        "hypothesis": exp.hypothesis.description if exp.hypothesis else "—",
                        "state": exp.state.value,
                        "metrics": exp.result.metrics if exp.result else {},
                        "config": exp.config,
                    }
                )
        return ToolResult(data={"comparison": rows, "count": len(rows)})

    return [
        ToolDef(
            name="run_experiment",
            description=(
                "Run a single train+evaluate experiment in one subprocess. "
                "Pass `train_code` as a Python module that defines "
                "`def train(X_train, y_train, X_test, *, artifacts_dir) -> y_pred` "
                "returning the task-specific output (regression: a flat list of "
                "float predictions for X_test, in input order). The framework "
                "loads the data once and calls your train function with the "
                "splits — DO NOT call `load_data()` from inside train. After "
                "train returns, the framework calls the canonical "
                "`evaluate(y_pred, X_train=..., X_test=..., y_train=..., "
                "y_test=..., artifacts_dir=...)` and records the metrics. "
                "Both train and evaluate share the same `artifacts_dir` — "
                "anything written there is archived for the experiment."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "domain_id": {
                        "type": "string",
                        "description": "The domain this experiment belongs to.",
                    },
                    "hypothesis": {
                        "type": "string",
                        "description": "What this experiment tests, in one sentence.",
                    },
                    "train_code": {
                        "type": "string",
                        "description": (
                            "Python source defining "
                            "`def train(X_train, y_train, X_test, *, "
                            "artifacts_dir) -> y_pred`. Returns a flat list of "
                            "float predictions for X_test in input order. The "
                            "framework supplies the data — do NOT call "
                            "`load_data()` from inside `train`. `artifacts_dir` "
                            "is a writable Path; saving to it is optional and "
                            "the agent's call (model checkpoints, training "
                            "plots). May use any standard libs available in "
                            "the workspace."
                        ),
                    },
                    "variables": {
                        "type": "object",
                        "description": (
                            "Optional hypothesis variables (e.g. {'model': "
                            "'ridge', 'alpha': 1.0}). Recorded for "
                            "traceability; not used by the runner."
                        ),
                    },
                },
                "required": ["domain_id", "hypothesis", "train_code"],
            },
            handler=run_experiment,
        ),
        ToolDef(
            name="get_experiment",
            description=(
                "Get full details of an experiment including its state, "
                "hypothesis, config, and results."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "experiment_id": {"type": "string"},
                },
                "required": ["experiment_id"],
            },
            handler=get_experiment,
        ),
        ToolDef(
            name="list_experiments",
            description="List all experiments, optionally filtered by domain ID.",
            parameters={
                "type": "object",
                "properties": {
                    "domain_id": {"type": "string"},
                },
            },
            handler=list_experiments,
        ),
        ToolDef(
            name="compare_experiments",
            description=(
                "Compare metrics across multiple experiments side by side. "
                "Use this to evaluate which approach works best."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "experiment_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["experiment_ids"],
            },
            handler=compare_experiments,
        ),
    ]


async def _ingest_artifacts(
    *,
    lab: LabEnvironment,
    experiment_id: str,
    artifacts_dir: Path,
) -> list[str]:
    """Walk the per-run artifacts dir, register each file with ArtifactStore,
    and forward to the tracking connector. Returns the list of stored
    artifact keys (suitable for CodeRun.artifact_paths). Failures are logged
    and swallowed so artifact-ingestion problems never fail the run.
    """
    paths: list[str] = []
    if not artifacts_dir.exists():
        return paths
    for file in sorted(artifacts_dir.rglob("*")):
        if not file.is_file():
            continue
        relative = file.relative_to(artifacts_dir).as_posix()
        key = f"experiments/{experiment_id}/artifacts/{relative}"
        try:
            await lab.artifact_store.save(key, file.read_bytes())
        except Exception as exc:
            logger.warning(
                "artifact_ingest_failed",
                experiment_id=experiment_id,
                file=str(file),
                error=str(exc),
            )
            continue
        paths.append(key)
        try:
            await lab.tracking.log_artifact(experiment_id, str(file))
        except Exception as exc:
            logger.warning(
                "artifact_track_failed",
                experiment_id=experiment_id,
                file=str(file),
                error=str(exc),
            )
    return paths


async def _finalise_experiment(
    *,
    service: ExperimentService,
    experiment: Experiment,
    domain_task_config: dict[str, Any],
    outcome: RunnerOutcome,
    exec_result: Any,
    run_number: int,
) -> ToolResult:
    """Translate the runner outcome into an experiment state transition + tool result."""
    assert experiment.result is not None

    if outcome.kind == "metrics":
        expected = set(domain_task_config.get("expected_metrics") or [])
        if expected:
            extras = set(outcome.metrics) - expected
            if extras:
                msg = (
                    f"evaluate returned unexpected metric keys {sorted(extras)} "
                    f"(expected: {sorted(expected)})"
                )
                experiment.result.error = msg
                await service.fail(experiment, msg)
                return ToolResult(
                    data={
                        "experiment_id": experiment.id,
                        "status": "failed",
                        "error": msg,
                        "stdout": exec_result.stdout,
                        "stderr": exec_result.stderr,
                        "exit_code": exec_result.exit_code,
                        "run_number": run_number,
                    }
                )
        experiment.result.metrics = outcome.metrics
        await service.complete(experiment)
        return ToolResult(
            data={
                "experiment_id": experiment.id,
                "status": "completed",
                "metrics": experiment.result.metrics,
                "stdout": exec_result.stdout,
                "stderr": exec_result.stderr,
                "exit_code": exec_result.exit_code,
                "run_number": run_number,
            }
        )

    if outcome.kind == "error":
        msg = (
            f"{outcome.error.get('type', 'Exception')}: "
            f"{outcome.error.get('message', '')}\n\n"
            f"{outcome.error.get('traceback', '')[:2000]}"
        )
    else:
        msg = format_runner_error(exec_result.stdout, exec_result.stderr, exec_result.exit_code)

    experiment.result.error = msg
    await service.fail(experiment, msg)
    return ToolResult(
        data={
            "experiment_id": experiment.id,
            "status": "failed",
            "error": msg,
            "stdout": exec_result.stdout,
            "stderr": exec_result.stderr,
            "exit_code": exec_result.exit_code,
            "run_number": run_number,
        }
    )
