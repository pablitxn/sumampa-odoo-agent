"""Unit tests for the stateful sales demo layer."""

from __future__ import annotations

import pytest

from sumampa_odoo_agent.services.demo_sales import (
    DemoSalesBridge,
    DemoSalesScenarioLockedError,
    DemoSalesScenarioRepository,
    DemoSalesSession,
    DemoSalesSessionStore,
)


def _session() -> tuple[DemoSalesSessionStore, DemoSalesSession]:
    scenarios = DemoSalesScenarioRepository.from_default()
    resolved = scenarios.resolve(scenario_id="interested-lead", params={})
    store = DemoSalesSessionStore()
    session = store.get_or_create(conversation_id="conversation-1", resolved=resolved)
    return store, session


def test_scenario_loading_validates_params_and_clones_initial_state() -> None:
    scenarios = DemoSalesScenarioRepository.from_default()

    first = scenarios.resolve(
        scenario_id="activation-link-missing",
        params={"activation_link_status": "available", "payment_state": "paid"},
    )
    first.initial_state["lead"]["name"] = "Changed"
    second = scenarios.resolve(scenario_id="activation-link-missing", params={})

    assert first.params["payment_state"] == "paid"
    assert first.initial_state["payment"]["state"] == "paid"
    assert first.initial_state["lead"]["commercial_state"] == "post_payment"
    assert second.initial_state["lead"]["name"] == "Mercado Centro"
    assert second.initial_state["activation"]["activation_link"] is None


def test_new_lead_empty_scenario_starts_with_unset_odoo_statuses() -> None:
    scenarios = DemoSalesScenarioRepository.from_default()

    resolved = scenarios.resolve(scenario_id="new-lead-empty", params={})

    assert resolved.params == {
        "control_state": "unset",
        "commercial_state": "unset",
        "payment_state": "unset",
        "subscription_state": "unset",
        "activation_link_status": "unset",
        "contact_role": "unset",
        "followup_state": "unset",
    }
    assert resolved.initial_state["lead"]["commercial_state"] is None
    assert resolved.initial_state["lead"]["contact_role"] is None
    assert resolved.initial_state["payment"]["state"] is None
    assert resolved.initial_state["subscription"]["state"] is None
    assert resolved.initial_state["activation"]["link_status"] is None
    assert resolved.initial_state["activation"]["activation_link"] is None
    assert resolved.initial_state["followup"]["state"] is None


def test_session_store_reuses_mutable_state_and_locks_scenario_params() -> None:
    scenarios = DemoSalesScenarioRepository.from_default()
    resolved = scenarios.resolve(scenario_id="interested-lead", params={})
    store = DemoSalesSessionStore()
    session = store.get_or_create(conversation_id="conversation-1", resolved=resolved)
    session.current_state["lead"]["commercial_state"] = "proposal_sent"

    reused = store.get_or_create(conversation_id="conversation-1", resolved=resolved)

    assert reused.current_state["lead"]["commercial_state"] == "proposal_sent"

    changed = scenarios.resolve(
        scenario_id="interested-lead",
        params={"commercial_state": "new"},
    )
    with pytest.raises(DemoSalesScenarioLockedError):
        store.get_or_create(conversation_id="conversation-1", resolved=changed)


@pytest.mark.asyncio
async def test_sales_bridge_records_opt_out_side_effects() -> None:
    _, session = _session()
    bridge = DemoSalesBridge(session, turn_id="turn-1")

    result = await bridge.execute_sales_tool("record_opt_out", {"reason": "stop"})

    assert result["ok"] is True
    assert session.current_state["lead"]["opted_out"] is True
    assert session.current_state["lead"]["followup_disabled"] is True
    assert session.current_state["followup"]["state"] == "disabled"
    assert session.current_state["tool_ledger"][-1]["tool"] == "execute_sales_tool"


@pytest.mark.asyncio
async def test_sales_bridge_requests_human_review() -> None:
    _, session = _session()
    bridge = DemoSalesBridge(session, turn_id="turn-1")

    result = await bridge.execute_sales_tool(
        "request_human_review",
        {"reason": "custom pricing", "priority": "high"},
    )

    assert result["priority"] == "high"
    assert session.current_state["lead"]["human_review_requested"] is True
    assert session.current_state["lead"]["control_state"] == "human_review"
    assert "human-review" in session.current_state["lead"]["tags"]


@pytest.mark.asyncio
async def test_sales_bridge_sets_interest_tags() -> None:
    _, session = _session()
    bridge = DemoSalesBridge(session, turn_id="turn-1")

    await bridge.execute_sales_tool("set_interest_tags", {"tags": ["rice", "bulk-pricing"]})

    assert "rice" in session.current_state["lead"]["interest_tags"]
    assert session.current_state["lead"]["interest_tags"].count("bulk-pricing") == 1


@pytest.mark.asyncio
async def test_sales_bridge_updates_commercial_state() -> None:
    _, session = _session()
    bridge = DemoSalesBridge(session, turn_id="turn-1")

    result = await bridge.execute_sales_tool(
        "update_lead_commercial_state",
        {"commercial_state": "proposal_sent"},
    )

    assert result["ok"] is True
    assert session.current_state["lead"]["commercial_state"] == "proposal_sent"


@pytest.mark.asyncio
async def test_sales_bridge_schedules_followup() -> None:
    _, session = _session()
    bridge = DemoSalesBridge(session, turn_id="turn-1")
    before_count = session.current_state["followup"]["count"]

    result = await bridge.execute_sales_tool(
        "schedule_followup",
        {"window": "tomorrow_morning"},
    )

    assert result["followup_state"] == "scheduled"
    assert session.current_state["followup"]["window"] == "tomorrow_morning"
    assert session.current_state["followup"]["count"] == before_count + 1
    assert session.current_state["lead"]["followup_disabled"] is False
