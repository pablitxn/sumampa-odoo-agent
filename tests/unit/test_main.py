"""Unit tests for service entrypoint."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sumampa_odoo_agent import main as main_module


def test_build_parser_handles_known_flags() -> None:
    parser = main_module.build_parser()

    default_args = parser.parse_args([])
    reload_args = parser.parse_args(["--reload"])

    assert default_args.reload is False
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
            "app": "sumampa_odoo_agent.api.main:app",
            "host": "127.0.0.1",
            "port": 9090,
            "reload": True,
        }
    ]


def test_main_runs_api_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []

    class _FakeParser:
        def parse_args(self) -> SimpleNamespace:
            return SimpleNamespace(reload=True)

    monkeypatch.setattr("sumampa_odoo_agent.main.build_parser", lambda: _FakeParser())
    monkeypatch.setattr("sumampa_odoo_agent.main.run_api", lambda reload: events.append(f"api:{reload}"))

    main_module.main()

    assert events == ["api:True"]
