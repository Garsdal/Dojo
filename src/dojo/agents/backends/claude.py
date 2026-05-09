"""Claude Agent SDK backend — runs agent sessions via ClaudeSDKClient."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from dojo.agents.backend import AgentBackend
from dojo.agents.types import AgentEvent, AgentRunConfig
from dojo.tools.adapters.claude import ClaudeToolAdapter
from dojo.tools.base import ToolDef
from dojo.utils.logging import get_logger

logger = get_logger(__name__)

# Claude Code built-in tools the agent may use
BUILTIN_TOOLS = ["Bash", "Read", "Write", "Edit", "WebFetch"]


class ClaudeAgentBackend(AgentBackend):
    """Runs an agent session using the Claude Agent SDK.

    Uses ClaudeToolAdapter from v1 to convert ToolDefs -> Claude MCP tools.
    Uses ClaudeSDKClient for session management, streaming, and interruption.
    """

    def __init__(self, *, model: str | None = None) -> None:
        """Construct a Claude backend.

        Args:
            model: Optional model id (e.g. ``"claude-sonnet-4-6"``). When set,
                ``complete()`` passes ``--model <id>`` to the ``claude`` CLI so
                tool generation uses a known, capable model rather than
                whatever the user has configured as the local default.
        """
        self._client: Any = None
        self._options: Any = None
        self._tool_adapter = ClaudeToolAdapter()
        self._tool_defs: list[ToolDef] = []
        self._model = model

    async def configure(
        self,
        tool_defs: list[ToolDef],
        config: AgentRunConfig,
    ) -> None:
        """Configure the Claude agent session.

        Converts ToolDefs to Claude format via ClaudeToolAdapter,
        builds ClaudeAgentOptions with the system prompt and limits.
        """
        from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

        self._tool_defs = tool_defs

        # Use the v1 ClaudeToolAdapter to create the MCP server
        server = self._tool_adapter.create_server("dojo", tool_defs)
        allowed_dojo = self._tool_adapter.tool_names_prefixed("dojo", tool_defs)

        self._options = ClaudeAgentOptions(
            mcp_servers={"dojo": server},
            allowed_tools=[*allowed_dojo, *BUILTIN_TOOLS],
            system_prompt=config.system_prompt,
            permission_mode=config.permission_mode,
            max_turns=config.max_turns,
            max_budget_usd=config.max_budget_usd,
            cwd=config.cwd,
        )

        self._client = ClaudeSDKClient(options=self._options)

    async def execute(self, prompt: str) -> AsyncIterator[AgentEvent]:
        """Execute the agent run, yielding events as they arrive."""
        if not self._client:
            msg = "Backend not configured — call configure() first"
            raise RuntimeError(msg)

        from claude_agent_sdk import (
            AssistantMessage,
            ResultMessage,
            TextBlock,
            ToolResultBlock,
            ToolUseBlock,
        )

        try:
            async with self._client as client:
                await client.query(prompt)

                async for message in client.receive_response():
                    events = self._message_to_events(
                        message,
                        AssistantMessage=AssistantMessage,
                        ToolUseBlock=ToolUseBlock,
                        ToolResultBlock=ToolResultBlock,
                        TextBlock=TextBlock,
                    )
                    for event in events:
                        yield event

                    # If this is the result message, yield the summary event
                    if isinstance(message, ResultMessage):
                        yield AgentEvent(
                            event_type="result",
                            data={
                                "session_id": message.session_id,
                                "turns": message.num_turns,
                                "cost_usd": message.total_cost_usd,
                                "duration_ms": message.duration_ms,
                                "is_error": message.is_error,
                            },
                        )

        except Exception as e:
            logger.error("claude_backend_error", error=str(e))
            yield AgentEvent(
                event_type="error",
                data={"error": str(e)},
            )

    async def stop(self) -> None:
        """Interrupt the Claude agent session."""
        if self._client:
            await self._client.interrupt()

    async def complete(self, prompt: str) -> str:
        """One-shot completion via the claude CLI subprocess.

        Uses the same auth path as agent runs — no ANTHROPIC_API_KEY needed.
        Passes ``--model <id>`` when a model was specified at construction.
        """
        import asyncio
        import os

        argv = ["claude", "-p"]
        if self._model:
            argv.extend(["--model", self._model])
        argv.append(prompt)

        # Strip CLAUDECODE so the CLI's nested-session guard doesn't trip when
        # the parent process was itself launched from a Claude Code shell. The
        # guard exists to prevent recursive interactive sessions; a deliberate
        # `claude -p` shell-out is fine and the CLI itself documents this var
        # as the bypass.
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300.0)
        if proc.returncode != 0:
            # Some claude-CLI errors (notably the nested-session guard) print
            # to stdout with empty stderr — fall back so the message survives.
            err = stderr.decode().strip() or stdout.decode().strip()
            raise RuntimeError(f"claude -p failed (exit {proc.returncode}): {err}")
        return stdout.decode().strip()

    @property
    def model(self) -> str | None:
        """Model id used for ``complete()`` (None means CLI default)."""
        return self._model

    @property
    def name(self) -> str:
        return "claude"

    # --- Private helpers ---

    @staticmethod
    def _message_to_events(
        message: Any,
        *,
        AssistantMessage: type,
        ToolUseBlock: type,
        ToolResultBlock: type,
        TextBlock: type,
    ) -> list[AgentEvent]:
        """Convert a Claude SDK message to AgentEvent(s).

        A single AssistantMessage may contain multiple content blocks,
        so we return a list.
        """
        events: list[AgentEvent] = []

        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, ToolUseBlock):
                    events.append(
                        AgentEvent(
                            event_type="tool_call",
                            data={"tool": block.name, "input": block.input},
                        )
                    )
                elif isinstance(block, ToolResultBlock):
                    events.append(
                        AgentEvent(
                            event_type="tool_result",
                            data={
                                "tool_use_id": block.tool_use_id,
                                "content": block.content,
                            },
                        )
                    )
                elif isinstance(block, TextBlock):
                    events.append(
                        AgentEvent(
                            event_type="text",
                            data={"text": block.text},
                        )
                    )

        return events
