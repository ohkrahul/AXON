"""The 'brain': a thin wrapper over the Claude Agent SDK.

Holds one persistent conversation so AXON remembers context across turns
("open it" refers to whatever we were just talking about). Claude is given
ONLY our curated PC tools — `permission_mode='dontAsk'` means any tool not in
`allowed_tools` (Bash, Write, Edit, …) is silently denied rather than run or
prompted for, which is exactly what you want for an unattended voice loop.
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


def _build_options() -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        system_prompt=config.PERSONA,
        model=config.MODEL,
        mcp_servers={pc_tools.SERVER_NAME: pc_tools.PC_SERVER},
        allowed_tools=pc_tools.ALLOWED_TOOL_NAMES,
        permission_mode="dontAsk",   # deny anything not pre-approved
        setting_sources=[],          # don't inherit the user's global CLAUDE.md/settings
    )


class Brain:
    """One long-lived Claude conversation."""

    def __init__(self) -> None:
        self._client: ClaudeSDKClient | None = None

    async def start(self) -> None:
        self._client = ClaudeSDKClient(options=_build_options())
        await self._client.connect()

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.disconnect()
            self._client = None

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

        reply = (final or " ".join(text_parts)).strip()
        return reply or "Sorry, I didn't catch that."

    async def __aenter__(self) -> "Brain":
        await self.start()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.stop()
