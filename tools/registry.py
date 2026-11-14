from dataclasses import dataclass
from typing import Any, Callable

from tools.knowledge_base import search_knowledge_base
from tools.service_status import check_service_status
from tools.ticket_manager import (
    create_support_ticket,
    reset_simulated_tickets
)


class ToolExecutionError(Exception):
    """Raised when a registered tool cannot be executed."""


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    function: Callable
    parameters: dict[str, Any]

    def to_llm_schema(self) -> dict:
        """Return an OpenAI-compatible function tool schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters
            }
        }


class ToolRegistry:
    """Shared registry for all agent modes."""

    def __init__(self, tools: list[ToolDefinition]):
        self._tools = {}

        for tool in tools:
            if tool.name in self._tools:
                raise ValueError(
                    f"Duplicate tool name: {tool.name}"
                )

            self._tools[tool.name] = tool

    def get_tool_names(self) -> list[str]:
        return list(self._tools.keys())

    def get_tool_descriptions(self) -> dict[str, str]:
        """
        Return name-to-description mapping for Jev Choice.

        The keys must match the actual executable tool names.
        """
        return {
            name: tool.description
            for name, tool in self._tools.items()
        }

    def get_llm_tool_schemas(self) -> list[dict]:
        """Return function schemas for the Groq LLM."""
        return [
            tool.to_llm_schema()
            for tool in self._tools.values()
        ]

    def get_tool(self, name: str) -> ToolDefinition:
        if name not in self._tools:
            raise ToolExecutionError(
                f"Unknown tool: {name}"
            )

        return self._tools[name]

    def execute(
        self,
        name: str,
        arguments: dict[str, Any]
    ) -> dict:
        """Validate arguments and execute a registered tool."""

        tool = self.get_tool(name)

        if not isinstance(arguments, dict):
            raise ToolExecutionError(
                "Tool arguments must be supplied as a dictionary."
            )

        properties = tool.parameters.get("properties", {})
        required = tool.parameters.get("required", [])

        missing = [
            key for key in required
            if key not in arguments
        ]

        unexpected = [
            key for key in arguments
            if key not in properties
        ]

        if missing:
            raise ToolExecutionError(
                f"Missing required arguments for {name}: {missing}"
            )

        if unexpected:
            raise ToolExecutionError(
                f"Unexpected arguments for {name}: {unexpected}"
            )

        try:
            result = tool.function(**arguments)

            if not isinstance(result, dict):
                raise TypeError(
                    "Tool functions must return dictionaries."
                )

            return result

        except ToolExecutionError:
            raise
        except Exception as exc:
            raise ToolExecutionError(
                f"Execution failed for {name}: {exc}"
            ) from exc

    def reset_state(self):
        """Reset mutable simulated state before a new experiment."""
        reset_simulated_tickets()


def build_default_registry() -> ToolRegistry:
    """Construct the common registry used by every agent mode."""

    tools = [
        ToolDefinition(
            name="search_knowledge_base",
            description=(
                "Search the local customer-support knowledge base "
                "for troubleshooting instructions and relevant FAQs."
            ),
            function=search_knowledge_base,
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Search terms describing the user's issue."
                        )
                    }
                },
                "required": ["query"],
                "additionalProperties": False
            }
        ),
        ToolDefinition(
            name="check_service_status",
            description=(
                "Check the fixed simulated operational status of a "
                "service such as internet, Wi-Fi, VPN, email, "
                "payment portal, or student portal."
            ),
            function=check_service_status,
            parameters={
                "type": "object",
                "properties": {
                    "service": {
                        "type": "string",
                        "description": (
                            "Name of the service whose status is requested."
                        )
                    }
                },
                "required": ["service"],
                "additionalProperties": False
            }
        ),
        ToolDefinition(
            name="create_support_ticket",
            description=(
                "Create a simulated in-memory customer-support ticket "
                "for an issue, with low, medium, or high priority."
            ),
            function=create_support_ticket,
            parameters={
                "type": "object",
                "properties": {
                    "issue": {
                        "type": "string",
                        "description": (
                            "A concise description of the support issue."
                        )
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                        "description": "Ticket priority."
                    }
                },
                "required": ["issue", "priority"],
                "additionalProperties": False
            }
        )
    ]

    return ToolRegistry(tools)
