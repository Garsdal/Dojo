"""Knowledge router — query knowledge atoms and their links."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from dojo.core.knowledge import KnowledgeAtom
from dojo.runtime.lab import LabEnvironment

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def _get_lab(request: Request) -> LabEnvironment:
    return request.app.state.lab


class KnowledgeResponse(BaseModel):
    """API response for a knowledge atom."""

    id: str
    domain_id: str = ""
    source_experiment_id: str = ""
    context: str
    claim: str
    action: str
    confidence: float
    evidence_ids: list[str] = []


class KnowledgeLinkResponse(BaseModel):
    """API response for a knowledge link."""

    id: str
    atom_id: str
    experiment_id: str
    domain_id: str
    link_type: str
    related_atom_id: str | None = None


class KnowledgeDetailResponse(BaseModel):
    """Detailed atom response with links."""

    atom: KnowledgeResponse
    links: list[KnowledgeLinkResponse] = []


def _atom_to_response(atom: KnowledgeAtom) -> KnowledgeResponse:
    return KnowledgeResponse(
        id=atom.id,
        domain_id=atom.domain_id,
        source_experiment_id=atom.source_experiment_id,
        context=atom.context,
        claim=atom.claim,
        action=atom.action,
        confidence=atom.confidence,
        evidence_ids=atom.evidence_ids,
    )


@router.get("", response_model=list[KnowledgeResponse])
async def list_knowledge(request: Request, domain_id: str | None = None) -> list[KnowledgeResponse]:
    """List all knowledge atoms, optionally filtered by domain."""
    lab = _get_lab(request)

    atoms = (
        await lab.memory_store.list_for_domain(domain_id)
        if domain_id
        else await lab.memory_store.list()
    )
    return [_atom_to_response(a) for a in atoms]


@router.get("/relevant", response_model=list[KnowledgeResponse])
async def search_knowledge(
    request: Request,
    query: str = "",
    limit: int = 10,
    domain_id: str | None = None,
) -> list[KnowledgeResponse]:
    """Search for relevant knowledge atoms, optionally scoped to a domain."""
    lab = _get_lab(request)

    atoms = await lab.memory_store.search(query, limit=limit, domain_id=domain_id or None)
    return [_atom_to_response(a) for a in atoms]


@router.get("/{atom_id}", response_model=KnowledgeDetailResponse)
async def get_knowledge(atom_id: str, request: Request) -> KnowledgeDetailResponse:
    """Get a knowledge atom with its links."""
    lab = _get_lab(request)
    atom = await lab.memory_store.get(atom_id)
    if atom is None:
        raise HTTPException(status_code=404, detail="Knowledge atom not found")

    raw_links = await lab.knowledge_linker.get_atom_links(atom_id)
    links = [
        KnowledgeLinkResponse(
            id=lnk.id,
            atom_id=lnk.atom_id,
            experiment_id=lnk.experiment_id,
            domain_id=lnk.domain_id,
            link_type=lnk.link_type.value,
            related_atom_id=lnk.related_atom_id,
        )
        for lnk in raw_links
    ]

    return KnowledgeDetailResponse(
        atom=_atom_to_response(atom),
        links=links,
    )


class CreateKnowledgeRequest(BaseModel):
    """Request body for creating a knowledge atom (goes through linker)."""

    context: str
    claim: str
    action: str = ""
    confidence: float = 0.5
    evidence_ids: list[str] = []
    experiment_id: str = ""
    domain_id: str = ""


class LinkingResultResponse(BaseModel):
    """Response from knowledge creation through the linker."""

    atom_id: str
    action: str  # always "created"
    confidence: float
    related_to: list[str] | None = None


@router.post("", response_model=LinkingResultResponse, status_code=201)
async def create_knowledge(body: CreateKnowledgeRequest, request: Request) -> LinkingResultResponse:
    """Create a new knowledge atom (goes through the knowledge linker)."""
    lab = _get_lab(request)

    result = await lab.knowledge_linker.produce_knowledge(
        context=body.context,
        claim=body.claim,
        action=body.action,
        confidence=body.confidence,
        evidence_ids=body.evidence_ids,
        experiment_id=body.experiment_id,
        domain_id=body.domain_id,
    )
    return LinkingResultResponse(
        atom_id=result.atom_id,
        action=result.action,
        confidence=result.confidence,
        related_to=result.related_to,
    )


@router.delete("/{atom_id}", status_code=204)
async def delete_knowledge(atom_id: str, request: Request) -> None:
    """Delete a knowledge atom by ID."""
    lab = _get_lab(request)
    deleted = await lab.memory_store.delete(atom_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Knowledge atom not found")
