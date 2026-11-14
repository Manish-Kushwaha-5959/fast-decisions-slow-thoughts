import pytest

from tools.knowledge_base import search_knowledge_base
from tools.service_status import check_service_status
from tools.ticket_manager import TicketManager
from tools.registry import (
    build_default_registry,
    ToolExecutionError
)


def test_knowledge_base_finds_password_article():
    result = search_knowledge_base("forgot password")

    assert result["result_count"] > 0
    assert result["results"][0]["id"] == "account_password_reset"


def test_knowledge_base_rejects_empty_query():
    with pytest.raises(ValueError):
        search_knowledge_base("")


def test_service_status_returns_vpn_status():
    result = check_service_status("vpn")

    assert result["service"] == "vpn"
    assert result["status"] == "degraded"
    assert result["source"] == "local_simulation"


def test_service_status_supports_alias():
    result = check_service_status("Wi-Fi")

    assert result["service"] == "wifi"
    assert result["status"] == "operational"


def test_unknown_service_returns_unknown():
    result = check_service_status("unknown_service")

    assert result["status"] == "unknown"


def test_ticket_manager_creates_ticket():
    manager = TicketManager()

    result = manager.create_ticket(
        issue="Cannot access student portal",
        priority="high"
    )

    assert result["ticket_id"] == "TICKET-0001"
    assert result["priority"] == "high"
    assert result["status"] == "created"

    assert len(manager.get_tickets()) == 1


def test_ticket_manager_rejects_invalid_priority():
    manager = TicketManager()

    with pytest.raises(ValueError):
        manager.create_ticket(
            issue="Cannot access portal",
            priority="urgent"
        )


def test_registry_exposes_all_tools():
    registry = build_default_registry()

    assert registry.get_tool_names() == [
        "search_knowledge_base",
        "check_service_status",
        "create_support_ticket"
    ]


def test_registry_executes_service_status():
    registry = build_default_registry()

    result = registry.execute(
        "check_service_status",
        {"service": "vpn"}
    )

    assert result["status"] == "degraded"


def test_registry_rejects_missing_arguments():
    registry = build_default_registry()

    with pytest.raises(ToolExecutionError):
        registry.execute(
            "search_knowledge_base",
            {}
        )


def test_registry_rejects_unknown_tool():
    registry = build_default_registry()

    with pytest.raises(ToolExecutionError):
        registry.execute(
            "unknown_tool",
            {}
        )


def test_registry_exposes_llm_schemas_and_jev_descriptions():
    registry = build_default_registry()

    llm_schemas = registry.get_llm_tool_schemas()
    jev_descriptions = registry.get_tool_descriptions()

    assert len(llm_schemas) == 3
    assert len(jev_descriptions) == 3

    schema_names = [
        item["function"]["name"]
        for item in llm_schemas
    ]

    assert schema_names == registry.get_tool_names()
    assert set(jev_descriptions) == set(registry.get_tool_names())


def test_registry_reset_state():
    registry = build_default_registry()

    first = registry.execute(
        "create_support_ticket",
        {
            "issue": "Test issue",
            "priority": "low"
        }
    )

    assert first["ticket_id"] == "TICKET-0001"

    registry.reset_state()

    second = registry.execute(
        "create_support_ticket",
        {
            "issue": "Another test issue",
            "priority": "medium"
        }
    )

    assert second["ticket_id"] == "TICKET-0001"
