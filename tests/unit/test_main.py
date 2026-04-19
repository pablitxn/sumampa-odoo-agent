"""Unit tests for service entrypoint."""

from __future__ import annotations

import runpy
import sys
from argparse import Namespace
from types import SimpleNamespace

import pytest

from sumampa_odoo_agent import main as main_module


def test_build_parser_handles_known_flags() -> None:
    parser = main_module.build_parser()

    default_args = parser.parse_args([])
    mcp_args = parser.parse_args(["--mcp"])
    reload_args = parser.parse_args(["--reload"])

    assert default_args.mcp is False
    assert default_args.reload is False
    assert mcp_args.mcp is True
    assert reload_args.reload is True


def test_run_api_uses_resolved_environment_and_uvicorn(monkeypatch: pytest.MonkeyPatch) -> None:
    uvicorn_calls: list[dict[str, object]] = []

    monkeypatch.setattr("sumampa_odoo_agent.main.resolve_environment", lambda: "test")
    monkeypatch.setattr(
        "sumampa_odoo_agent.main.load_settings",
        lambda **_: SimpleNamespace(
            service=SimpleNamespace(host="127.0.0.1", port=9090),
        ),
    )
    monkeypatch.setattr(
        "sumampa_odoo_agent.main.uvicorn.run",
        lambda app, host, port, reload: uvicorn_calls.append(
            {
                "app": app,
                "host": host,
                "port": port,
                "reload": reload,
            }
        ),
    )

    main_module.run_api(reload=True)

    assert uvicorn_calls == [
        {
            "app": "sumampa_odoo_agent.adapters.api.main:app",
            "host": "127.0.0.1",
            "port": 9090,
            "reload": True,
        }
    ]


def test_main_runs_mcp_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []

    class _FakeParser:
        def parse_args(self) -> Namespace:
            return Namespace(mcp=True, reload=False)

    async def fake_run_mcp_server() -> None:
        events.append("mcp_server")

    def fake_asyncio_run(coro: object) -> None:
        events.append("asyncio_run")
        assert hasattr(coro, "close")
        events.append("coro_received")
        coro.close()

    monkeypatch.setattr("sumampa_odoo_agent.main.build_parser", lambda: _FakeParser())
    monkeypatch.setattr("sumampa_odoo_agent.main.run_mcp_server", fake_run_mcp_server)
    monkeypatch.setattr("sumampa_odoo_agent.main.asyncio.run", fake_asyncio_run)
    monkeypatch.setattr("sumampa_odoo_agent.main.run_api", lambda reload: events.append(f"api:{reload}"))

    main_module.main()

    assert events == ["asyncio_run", "coro_received"]


def test_main_runs_api_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []

    class _FakeParser:
        def parse_args(self) -> Namespace:
            return Namespace(mcp=False, reload=True)

    monkeypatch.setattr("sumampa_odoo_agent.main.build_parser", lambda: _FakeParser())
    monkeypatch.setattr("sumampa_odoo_agent.main.run_api", lambda reload: events.append(f"api:{reload}"))
    monkeypatch.setattr(
        "sumampa_odoo_agent.main.asyncio.run",
        lambda coro: events.append("asyncio_run_unexpected"),
    )

    main_module.main()

    assert events == ["api:True"]


def test_main_module_entrypoint_executes_main_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []

    async def fake_run_mcp_server() -> None:
        events.append("mcp_server")

    monkeypatch.setattr(sys, "argv", ["sumampa_odoo_agent.main", "--mcp"])
    monkeypatch.setattr("sumampa_odoo_agent.adapters.mcp.run_mcp_server", fake_run_mcp_server)

    runpy.run_path(main_module.__file__, run_name="__main__")

    assert events == ["mcp_server"]
