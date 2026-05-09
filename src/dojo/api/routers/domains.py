"""Domains router — CRUD + tool management for research domains."""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from dojo.core.domain import Domain, DomainStatus, DomainTool, ToolType
from dojo.core.task import Task, TaskType
from dojo.runtime.domain_service import DomainService
from dojo.runtime.lab import LabEnvironment
from dojo.runtime.setup_loader import load_setup
from dojo.runtime.task_service import TaskFrozenError, TaskService, TaskVerificationError
from dojo.runtime.tool_verifier import verify_required_tools
from dojo.tools.tool_generation import (
    build_task_generation_prompt,
    build_tool_generation_prompt,
    dicts_to_domain_tools,
    parse_generated_tools,
)

router = APIRouter(prefix="/domains", tags=["domains"])


def _get_lab(request: Request) -> LabEnvironment:
    return request.app.state.lab


# --- Request / Response models ---


class DomainToolRequest(BaseModel):
    name: str
    description: str = ""
    type: str = "custom"
    example_usage: str = ""
    code: str = ""
    module_filename: str = ""
    entrypoint: str = ""
    created_by: str = "human"


class DomainToolResponse(BaseModel):
    id: str
    name: str
    description: str
    type: str
    example_usage: str
    code: str = ""
    module_filename: str = ""
    entrypoint: str = ""
    created_by: str
    created_at: str


class WorkspaceRequest(BaseModel):
    source: str = "local"
    path: str = ""
    git_url: str | None = None
    git_ref: str | None = None
    setup_script: str | None = None
    env_vars: dict[str, str] = {}


class WorkspaceResponse(BaseModel):
    path: str
    source: str
    ready: bool
    python_path: str | None
    git_url: str | None = None


class CreateDomainRequest(BaseModel):
    name: str
    description: str = ""
    prompt: str = ""
    config: dict[str, Any] = {}
    metadata: dict[str, Any] = {}
    tools: list[DomainToolRequest] = []
    workspace: WorkspaceRequest | None = None


class UpdateDomainRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    prompt: str | None = None
    status: str | None = None
    config: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


class DomainResponse(BaseModel):
    id: str
    name: str
    description: str
    prompt: str
    status: str
    config: dict[str, Any]
    metadata: dict[str, Any]
    experiment_ids: list[str]
    tools: list[DomainToolResponse]
    workspace: WorkspaceResponse | None = None
    created_at: str
    updated_at: str


def _tool_response(tool: DomainTool) -> DomainToolResponse:
    return DomainToolResponse(
        id=tool.id,
        name=tool.name,
        description=tool.description,
        type=tool.type.value,
        example_usage=tool.example_usage,
        code=tool.code,
        module_filename=tool.module_filename,
        entrypoint=tool.entrypoint,
        created_by=tool.created_by,
        created_at=tool.created_at.isoformat(),
    )


def _domain_tools(domain: Domain) -> list[DomainTool]:
    """Phase 4: tools live on ``domain.task.tools``. None if no task."""
    return list(domain.task.tools) if domain.task is not None else []


def _domain_response(domain: Domain) -> DomainResponse:
    workspace = None
    if domain.workspace is not None:
        workspace = WorkspaceResponse(
            path=domain.workspace.path,
            source=domain.workspace.source.value,
            ready=domain.workspace.ready,
            python_path=domain.workspace.python_path,
            git_url=domain.workspace.git_url,
        )
    return DomainResponse(
        id=domain.id,
        name=domain.name,
        description=domain.description,
        prompt=domain.prompt,
        status=domain.status.value,
        config=domain.config,
        metadata=domain.metadata,
        experiment_ids=domain.experiment_ids,
        tools=[_tool_response(t) for t in _domain_tools(domain)],
        workspace=workspace,
        created_at=domain.created_at.isoformat(),
        updated_at=domain.updated_at.isoformat(),
    )


# --- Domain CRUD ---


@router.post("", response_model=DomainResponse, status_code=201)
async def create_domain(body: CreateDomainRequest, request: Request) -> DomainResponse:
    from dojo.core.domain import Workspace, WorkspaceSource

    lab = _get_lab(request)
    service = DomainService(lab)

    tools = [
        DomainTool(
            name=t.name,
            description=t.description,
            type=ToolType(t.type),
            example_usage=t.example_usage,
            code=t.code,
            module_filename=t.module_filename,
            entrypoint=t.entrypoint,
            created_by=t.created_by,
        )
        for t in body.tools
    ]

    workspace = None
    if body.workspace is not None:
        workspace = Workspace(
            source=WorkspaceSource(body.workspace.source),
            path=body.workspace.path,
            git_url=body.workspace.git_url,
            git_ref=body.workspace.git_ref,
            setup_script=body.workspace.setup_script,
            env_vars=body.workspace.env_vars,
        )

    # Phase 4: tools live on the task. Attach as a draft (unfrozen) task so
    # the create-domain payload survives until `dojo task setup` runs.
    task = Task(tools=tools) if tools else None

    domain = Domain(
        name=body.name,
        description=body.description,
        prompt=body.prompt,
        status=DomainStatus.ACTIVE,
        config=body.config,
        metadata=body.metadata,
        task=task,
        workspace=workspace,
    )
    await service.create(domain)
    return _domain_response(domain)


@router.get("", response_model=list[DomainResponse])
async def list_domains(request: Request) -> list[DomainResponse]:
    lab = _get_lab(request)
    service = DomainService(lab)
    domains = await service.list()
    return [_domain_response(d) for d in domains]


@router.get("/{domain_id}", response_model=DomainResponse)
async def get_domain(domain_id: str, request: Request) -> DomainResponse:
    lab = _get_lab(request)
    service = DomainService(lab)
    domain = await service.get(domain_id)
    if domain is None:
        raise HTTPException(status_code=404, detail="Domain not found")
    return _domain_response(domain)


@router.put("/{domain_id}", response_model=DomainResponse)
async def update_domain(
    domain_id: str, body: UpdateDomainRequest, request: Request
) -> DomainResponse:
    lab = _get_lab(request)
    service = DomainService(lab)
    domain = await service.get(domain_id)
    if domain is None:
        raise HTTPException(status_code=404, detail="Domain not found")

    if body.name is not None:
        domain.name = body.name
    if body.description is not None:
        domain.description = body.description
    if body.prompt is not None:
        domain.prompt = body.prompt
    if body.status is not None:
        domain.status = DomainStatus(body.status)
    if body.config is not None:
        domain.config = body.config
    if body.metadata is not None:
        domain.metadata = body.metadata

    await service.update(domain)
    return _domain_response(domain)


@router.delete("/{domain_id}", status_code=204)
async def delete_domain(domain_id: str, request: Request) -> None:
    lab = _get_lab(request)
    service = DomainService(lab)
    deleted = await service.delete(domain_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Domain not found")


# --- Domain Tools ---


@router.post("/{domain_id}/tools", response_model=DomainToolResponse, status_code=201)
async def add_domain_tool(
    domain_id: str, body: DomainToolRequest, request: Request
) -> DomainToolResponse:
    lab = _get_lab(request)
    service = DomainService(lab)

    tool = DomainTool(
        name=body.name,
        description=body.description,
        type=ToolType(body.type),
        example_usage=body.example_usage,
        code=body.code,
        module_filename=body.module_filename,
        entrypoint=body.entrypoint,
        created_by=body.created_by,
    )
    await service.add_tool(domain_id, tool)
    return _tool_response(tool)


@router.get("/{domain_id}/tools", response_model=list[DomainToolResponse])
async def list_domain_tools(domain_id: str, request: Request) -> list[DomainToolResponse]:
    lab = _get_lab(request)
    service = DomainService(lab)
    domain = await service.get(domain_id)
    if domain is None:
        raise HTTPException(status_code=404, detail="Domain not found")
    return [_tool_response(t) for t in _domain_tools(domain)]


@router.delete("/{domain_id}/tools/{tool_id}", status_code=204)
async def remove_domain_tool(domain_id: str, tool_id: str, request: Request) -> None:
    lab = _get_lab(request)
    service = DomainService(lab)
    try:
        await service.remove_tool(domain_id, tool_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Domain not found") from exc


# --- Domain Experiments ---


@router.get("/{domain_id}/experiments")
async def list_domain_experiments(domain_id: str, request: Request) -> list[dict]:
    lab = _get_lab(request)
    experiments = await lab.experiment_store.list(domain_id=domain_id)
    return [
        {
            "id": exp.id,
            "domain_id": exp.domain_id,
            "state": exp.state.value,
            "hypothesis": exp.hypothesis.description if exp.hypothesis else None,
            "config": exp.config,
            "metrics": exp.result.metrics if exp.result else None,
            "error": exp.result.error if exp.result else None,
            "created_at": exp.created_at.isoformat(),
        }
        for exp in experiments
    ]


# --- Domain Metrics Evolution ---


@router.get("/{domain_id}/metrics")
async def domain_metrics_evolution(domain_id: str, request: Request) -> dict:
    """Aggregate metrics across all experiments in a domain."""
    lab = _get_lab(request)
    experiments = await lab.experiment_store.list(domain_id=domain_id)

    metrics_over_time = []
    for exp in sorted(experiments, key=lambda e: e.created_at):
        if exp.result and exp.result.metrics:
            metrics_over_time.append(
                {
                    "experiment_id": exp.id,
                    "timestamp": exp.created_at.isoformat(),
                    "metrics": exp.result.metrics,
                }
            )

    return {"domain_id": domain_id, "metrics_evolution": metrics_over_time}


# --- Domain Knowledge ---


@router.get("/{domain_id}/knowledge")
async def list_domain_knowledge(domain_id: str, request: Request) -> list[dict]:
    """All knowledge atoms linked to a domain."""
    lab = _get_lab(request)

    atoms = await lab.knowledge_linker.get_domain_knowledge(domain_id)
    return [
        {
            "id": a.id,
            "domain_id": a.domain_id,
            "source_experiment_id": a.source_experiment_id,
            "context": a.context,
            "claim": a.claim,
            "action": a.action,
            "confidence": a.confidence,
            "evidence_ids": a.evidence_ids,
        }
        for a in atoms
    ]


# --- Workspace Management ---


@router.post("/{domain_id}/workspace/setup", status_code=202)
async def setup_workspace(domain_id: str, request: Request) -> dict:
    """Trigger workspace setup for a domain (one-time operation).

    Resolves the workspace path, creates a virtual environment,
    and installs dependencies. Returns 202 and runs setup synchronously.
    """
    from dojo.config.settings import Settings
    from dojo.runtime.workspace_service import WorkspaceService

    lab = _get_lab(request)
    service = DomainService(lab)
    domain = await service.get(domain_id)
    if domain is None:
        raise HTTPException(status_code=404, detail="Domain not found")
    if domain.workspace is None:
        raise HTTPException(status_code=400, detail="Domain has no workspace configured")

    settings: Settings = request.app.state.settings
    ws_service = WorkspaceService(settings.storage.base_dir)
    try:
        workspace = await ws_service.setup(domain)
        domain.workspace = workspace
        await service.update(domain)
        return {"status": "ready", "path": workspace.path, "python_path": workspace.python_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Workspace setup failed: {e}") from e


@router.get("/{domain_id}/workspace/status")
async def workspace_status(domain_id: str, request: Request) -> dict:
    """Get workspace setup status for a domain."""
    from dojo.config.settings import Settings
    from dojo.runtime.workspace_service import WorkspaceService

    lab = _get_lab(request)
    service = DomainService(lab)
    domain = await service.get(domain_id)
    if domain is None:
        raise HTTPException(status_code=404, detail="Domain not found")

    if domain.workspace is None:
        return {"configured": False}

    settings: Settings = request.app.state.settings
    ws_service = WorkspaceService(settings.storage.base_dir)
    return ws_service.get_status(domain.workspace)


@router.post("/{domain_id}/workspace/validate")
async def validate_workspace(domain_id: str, request: Request) -> dict:
    """Validate that the workspace is functional."""
    from dojo.config.settings import Settings
    from dojo.runtime.workspace_service import WorkspaceService

    lab = _get_lab(request)
    service = DomainService(lab)
    domain = await service.get(domain_id)
    if domain is None:
        raise HTTPException(status_code=404, detail="Domain not found")
    if domain.workspace is None:
        raise HTTPException(status_code=400, detail="Domain has no workspace configured")

    settings: Settings = request.app.state.settings
    ws_service = WorkspaceService(settings.storage.base_dir)
    return await ws_service.validate(domain)


@router.post("/{domain_id}/workspace/scan")
async def scan_workspace(domain_id: str, request: Request) -> dict:
    """Scan the workspace and return tool suggestions."""
    from dojo.runtime.workspace_scanner import WorkspaceScanner

    lab = _get_lab(request)
    service = DomainService(lab)
    domain = await service.get(domain_id)
    if domain is None:
        raise HTTPException(status_code=404, detail="Domain not found")
    if domain.workspace is None or not domain.workspace.path:
        raise HTTPException(status_code=400, detail="Domain has no workspace configured")

    scanner = WorkspaceScanner()
    summary = scanner.get_summary(domain.workspace.path)
    suggestions = scanner.scan(domain.workspace.path)

    return {
        "summary": summary,
        "suggestions": [
            {
                "name": s.name,
                "description": s.description,
                "type": s.tool_type,
                "code": s.code,
                "example_usage": s.example_usage,
                "parameters": s.parameters,
            }
            for s in suggestions
        ],
    }


# --- AI Tool Generation ---


class GenerateToolsRequest(BaseModel):
    hint: str = ""


class VerificationResultResponse(BaseModel):
    verified: bool
    errors: list[str]
    sample_output: dict[str, Any] = {}
    duration_ms: float | None = None


class GeneratedToolResponse(BaseModel):
    name: str
    description: str
    type: str
    example_usage: str
    code: str = ""
    module_filename: str = ""
    entrypoint: str = ""
    verification: VerificationResultResponse | None = None


class GenerateToolsResponse(BaseModel):
    domain_id: str
    generated: list[GeneratedToolResponse]
    prompt_used: str
    raw_output: str | None = None


def _verification_response(tool: DomainTool) -> VerificationResultResponse | None:
    if tool.verification is None:
        return None
    v = tool.verification
    return VerificationResultResponse(
        verified=v.verified,
        errors=list(v.errors),
        sample_output=dict(v.sample_output),
        duration_ms=v.duration_ms,
    )


@router.post("/{domain_id}/tools/generate", response_model=GenerateToolsResponse)
async def generate_tools(
    domain_id: str, body: GenerateToolsRequest, request: Request
) -> GenerateToolsResponse:
    """AI-generate tool definitions for a domain, verify them, and persist.

    If the domain has a Task, generated tools land on ``domain.task.tools``
    and each is verified against its ToolContract before the response.
    Verification status is included so the client knows which tools are
    ready to freeze.
    """
    lab = _get_lab(request)
    service = DomainService(lab)
    domain = await service.get(domain_id)
    if domain is None:
        raise HTTPException(status_code=404, detail="Domain not found")
    if domain.task is not None and domain.task.frozen:
        raise HTTPException(
            status_code=409,
            detail="Task is frozen — unfreeze before regenerating tools",
        )

    if domain.task is not None:
        setup_md = load_setup(domain, base_dir=Path(lab.settings.storage.base_dir))
        prompt = build_task_generation_prompt(
            domain, domain.task, hint=body.hint, setup_md=setup_md
        )
    else:
        prompt = build_tool_generation_prompt(domain, hint=body.hint)

    from dojo.agents.factory import create_agent_backend

    backend = create_agent_backend(
        lab.settings.agent.backend,
        model=lab.settings.agent.tool_generation_model,
    )

    try:
        raw_output = await backend.complete(prompt)
    except (AttributeError, NotImplementedError):
        return GenerateToolsResponse(
            domain_id=domain_id,
            generated=[],
            prompt_used=prompt,
            raw_output=None,
        )

    try:
        tool_dicts = parse_generated_tools(raw_output)
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail=f"Failed to parse generated tools: {e}",
        ) from e

    tools = dicts_to_domain_tools(tool_dicts)

    # Verify against the Task's contract (if any) — populates tool.verification.
    # We write modules to `.dojo/domains/{id}/sources/` first so the verifier
    # imports from a stable dir; cache files written by `load_data` persist
    # across calls instead of being thrown away with a tempdir.
    if domain.task is not None:
        sources_dir = TaskService(lab).sources_dir(domain.id)
        sources_dir.mkdir(parents=True, exist_ok=True)
        for tool in tools:
            if tool.module_filename and tool.code:
                (sources_dir / tool.module_filename).write_text(tool.code)
        await verify_required_tools(
            tools,
            domain.task,
            sandbox=lab.sandbox,
            workspace=domain.workspace,
            timeout=lab.settings.sandbox.verification_timeout,
            module_dir=sources_dir,
        )

    # Phase 4: tools live on the task only.
    if domain.task is not None:
        domain.task.tools = tools
    await service.update(domain)

    return GenerateToolsResponse(
        domain_id=domain_id,
        generated=[
            GeneratedToolResponse(
                name=t.name,
                description=t.description,
                type=t.type.value,
                example_usage=t.example_usage,
                code=t.code,
                module_filename=t.module_filename,
                entrypoint=t.entrypoint,
                verification=_verification_response(t),
            )
            for t in tools
        ],
        prompt_used=prompt,
        raw_output=raw_output,
    )


# --- Task management ---


class CreateTaskRequest(BaseModel):
    type: str = "regression"
    name: str = ""
    description: str = ""
    config: dict[str, Any] = {}


class UpdateTaskConfigRequest(BaseModel):
    config: dict[str, Any]


class TaskResponse(BaseModel):
    id: str
    type: str
    name: str
    description: str
    primary_metric: str
    direction: str
    tools: list[DomainToolResponse]
    config: dict[str, Any]
    frozen: bool
    created_at: str
    updated_at: str


def _task_response(task: Task) -> TaskResponse:
    return TaskResponse(
        id=task.id,
        type=task.type.value,
        name=task.name,
        description=task.description,
        primary_metric=task.primary_metric,
        direction=task.direction.value,
        tools=[_tool_response(t) for t in task.tools],
        config=task.config,
        frozen=task.frozen,
        created_at=task.created_at.isoformat(),
        updated_at=task.updated_at.isoformat(),
    )


@router.post("/{domain_id}/task", response_model=TaskResponse, status_code=201)
async def create_task(domain_id: str, body: CreateTaskRequest, request: Request) -> TaskResponse:
    """Create a Task on a domain (only one Task per Domain)."""
    lab = _get_lab(request)
    try:
        task_type = TaskType(body.type)
    except ValueError as exc:
        raise HTTPException(
            400, f"Unknown task type: {body.type!r}. Supported: regression"
        ) from exc
    svc = TaskService(lab)
    try:
        task = await svc.create(
            domain_id,
            task_type=task_type,
            name=body.name,
            description=body.description,
            config=body.config or None,
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return _task_response(task)


@router.get("/{domain_id}/task", response_model=TaskResponse)
async def get_task(domain_id: str, request: Request) -> TaskResponse:
    """Get the Task for a domain."""
    lab = _get_lab(request)
    task = await TaskService(lab).get(domain_id)
    if task is None:
        raise HTTPException(404, "No task configured for this domain")
    return _task_response(task)


@router.put("/{domain_id}/task/config", response_model=TaskResponse)
async def update_task_config(
    domain_id: str, body: UpdateTaskConfigRequest, request: Request
) -> TaskResponse:
    """Update task config fields (only allowed when task is not frozen)."""
    lab = _get_lab(request)
    try:
        task = await TaskService(lab).update_config(domain_id, body.config)
    except TaskFrozenError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return _task_response(task)


@router.post("/{domain_id}/task/freeze", response_model=TaskResponse)
async def freeze_task(
    domain_id: str,
    request: Request,
    skip_verification: bool = False,
) -> TaskResponse:
    """Freeze the task — required before any agent run can start.

    Rejects with 422 if the verification gate fails. Pass
    ``?skip_verification=true`` only when the user has explicitly opted out
    (e.g. ``--unsafe-skip-verify`` from the CLI).
    """
    lab = _get_lab(request)
    try:
        task = await TaskService(lab).freeze(domain_id, skip_verification=skip_verification)
    except TaskVerificationError as exc:
        raise HTTPException(
            422,
            detail={"message": str(exc), "errors": exc.errors},
        ) from exc
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return _task_response(task)


@router.post("/{domain_id}/task/unfreeze", response_model=TaskResponse)
async def unfreeze_task(domain_id: str, request: Request) -> TaskResponse:
    """Unfreeze the task to allow tool changes.

    Warning: if tool code changes after experiments have already run, those
    prior metrics may no longer be comparable to new ones.
    """
    lab = _get_lab(request)
    try:
        task = await TaskService(lab).unfreeze(domain_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return _task_response(task)


@router.delete("/{domain_id}/task", status_code=204)
async def delete_task(domain_id: str, request: Request) -> None:
    """Remove the task from a domain (only allowed when not frozen)."""
    lab = _get_lab(request)
    try:
        await TaskService(lab).delete(domain_id)
    except TaskFrozenError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
