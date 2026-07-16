"""The 'brain': a thin wrapper over the Claude Agent SDK.

Holds one persistent conversation so AXON remembers context across turns
("open it" refers to whatever we were just talking about). Claude is given
ONLY our curated PC tools — `permission_mode='dontAsk'` means any tool not in
`allowed_tools` (Bash, Write, Edit, …) is silently denied rather than run or
prompted for, which is exactly what you want for an unattended voice loop.

AXON can also switch its own model at runtime (see pc_tools.set_model): the
tool records a pending model, and we apply it between turns via the SDK's
`set_model`, so the switch never happens mid-response.
"""
from __future__ import annotations

from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    TextBlock,
    ResultMessage,
)

import config
import pc_tools

# The currently-running Brain, so tools (which run in this process) can reach
# it to switch models. Set in start().
ACTIVE_BRAIN: "Brain | None" = None


class Brain:
    """One long-lived Claude conversation."""

    def __init__(self) -> None:
        self._client: ClaudeSDKClient | None = None
        self.model: str = config.MODEL
        self._pending_model: str | None = None

    def _options(self) -> ClaudeAgentOptions:
        return ClaudeAgentOptions(
            system_prompt=config.PERSONA,
            model=self.model,
            mcp_servers={pc_tools.SERVER_NAME: pc_tools.PC_SERVER},
            allowed_tools=pc_tools.ALLOWED_TOOL_NAMES,
            permission_mode="dontAsk",   # deny anything not pre-approved
            setting_sources=[],          # don't inherit global CLAUDE.md/settings
        )

    async def start(self) -> None:
        global ACTIVE_BRAIN
        self._client = ClaudeSDKClient(options=self._options())
        await self._client.connect()
        ACTIVE_BRAIN = self

    async def stop(self) -> None:
        global ACTIVE_BRAIN
        if self._client is not None:
            await self._client.disconnect()
            self._client = None
        if ACTIVE_BRAIN is self:
            ACTIVE_BRAIN = None

    def request_model(self, model_id: str) -> None:
        """Ask to switch models; applied after the current turn finishes."""
        self._pending_model = model_id

    async def ask(self, text: str) -> str:
        """Send one user utterance, return Claude's spoken reply as plain text."""
        if self._client is None:
            raise RuntimeError("Brain.start() was not called")

        await self._client.query(text)

        text_parts: list[str] = []
        final: str | None = None
        async for msg in self._client.receive_response():
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        text_parts.append(block.text)
            elif isinstance(msg, ResultMessage):
                final = getattr(msg, "result", None)

        # Apply a requested model switch between turns (safe point).
        if self._pending_model and self._pending_model != self.model:
            try:
                await self._client.set_model(self._pending_model)
                self.model = self._pending_model
            except Exception:  # noqa: BLE001
                pass
            self._pending_model = None

        reply = (final or " ".join(text_parts)).strip()
        return reply or "Sorry, I didn't catch that."

    async def __aenter__(self) -> "Brain":
        await self.start()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.stop()
