"""Request handlers for agent execution."""

from __future__ import annotations

from sumampa_odoo_agent.application.requests.agent import RunAgentCommand
from sumampa_odoo_agent.domain.ports.agent_port import AgentPort


class RunAgentCommandHandler:
    def __init__(self, agent: AgentPort) -> None:
        self._agent = agent

    async def handle(self, request: RunAgentCommand) -> dict[str, object]:
        return await self._agent.run(
            prompt=request.prompt,
            context=request.context,
            session_id=request.session_id,
        )
