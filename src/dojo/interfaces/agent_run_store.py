"""Agent run store interface."""

from abc import ABC, abstractmethod

from dojo.agents.types import AgentRun


class AgentRunStore(ABC):
    """Abstract base class for agent run persistence."""

    @abstractmethod
    async def save(self, run: AgentRun) -> str:
        """Persist an agent run, overwriting any existing record with the same ID."""

    @abstractmethod
    async def load(self, run_id: str) -> AgentRun | None:
        """Load a run by ID, returning None if not found."""

    @abstractmethod
    async def list(self) -> list[AgentRun]:
        """Return all persisted runs, sorted oldest-first."""

    @abstractmethod
    async def delete(self, run_id: str) -> bool:
        """Delete a run, returning True if it existed."""
