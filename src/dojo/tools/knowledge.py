"""Dojo.ml knowledge management tools."""

from typing import Any

from dojo.runtime.lab import LabEnvironment
from dojo.tools.base import ToolDef, ToolResult


def create_knowledge_tools(lab: LabEnvironment) -> list[ToolDef]:
    """Create all knowledge tools backed by a LabEnvironment."""

    async def write_knowledge(args: dict[str, Any]) -> ToolResult:
        result = await lab.knowledge_linker.produce_knowledge(
            context=args["context"],
            claim=args["claim"],
            action=args.get("action", ""),
            confidence=args.get("confidence", 0.5),
            evidence_ids=args.get("evidence_ids", []),
            experiment_id=args.get("experiment_id", ""),
            domain_id=args.get("domain_id", ""),
        )
        return ToolResult(
            data={
                "atom_id": result.atom_id,
                "action": result.action,
                "confidence": result.confidence,
                "related_to": result.related_to,
            }
        )

    async def search_knowledge(args: dict[str, Any]) -> ToolResult:
        atoms = await lab.memory_store.search(
            args["query"],
            limit=args.get("limit", 10),
            domain_id=args.get("domain_id") or None,
        )

        return ToolResult(
            data=[
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
        )

    async def list_knowledge(args: dict[str, Any]) -> ToolResult:
        domain_id = args.get("domain_id")
        if domain_id:
            atoms = await lab.memory_store.list_for_domain(domain_id)
        else:
            atoms = await lab.memory_store.list()

        return ToolResult(
            data=[
                {
                    "id": a.id,
                    "domain_id": a.domain_id,
                    "source_experiment_id": a.source_experiment_id,
                    "context": a.context,
                    "claim": a.claim,
                    "action": a.action,
                    "confidence": a.confidence,
                }
                for a in atoms
            ]
        )

    return [
        ToolDef(
            name="write_knowledge",
            description=(
                "Record a durable finding worth carrying into future runs of this "
                "domain. Each call creates a new immutable atom; similar atoms are "
                "auto-linked via RELATED_TO. Use this when you've ruled out a class "
                "of approach, found a hyperparameter range that's dead, or confirmed "
                "a feature/preprocessing trick helps or hurts. Skip routine "
                "incremental tuning."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "context": {
                        "type": "string",
                        "description": "What situation/experiment this learning comes from",
                    },
                    "claim": {
                        "type": "string",
                        "description": "The factual claim or finding",
                    },
                    "action": {
                        "type": "string",
                        "description": "Recommended action based on this finding",
                    },
                    "confidence": {
                        "type": "number",
                        "description": "Confidence 0.0-1.0",
                    },
                    "evidence_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Experiment IDs that support this claim",
                    },
                    "experiment_id": {
                        "type": "string",
                        "description": "The experiment that produced this finding",
                    },
                    "domain_id": {
                        "type": "string",
                        "description": "The domain this knowledge belongs to",
                    },
                },
                "required": ["context", "claim"],
            },
            handler=write_knowledge,
        ),
        ToolDef(
            name="search_knowledge",
            description=(
                "Search for previously recorded knowledge atoms relevant to a query. "
                "Use this to recall prior learnings before starting a new experiment. "
                "Optionally filter by domain_id for domain-scoped search."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to search for",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default 10)",
                    },
                    "domain_id": {
                        "type": "string",
                        "description": "Optional: filter to knowledge linked to this domain",
                    },
                },
                "required": ["query"],
            },
            handler=search_knowledge,
        ),
        ToolDef(
            name="list_knowledge",
            description=(
                "List all recorded knowledge atoms. "
                "Optionally filter by domain_id for domain-scoped listing."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "domain_id": {
                        "type": "string",
                        "description": "Optional: filter to knowledge linked to this domain",
                    },
                },
            },
            handler=list_knowledge,
        ),
    ]
