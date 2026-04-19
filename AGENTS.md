# Repository Guidelines

## Project Structure & Module Organization
Code lives under `src/sumampa_odoo_agent`. Keep the hexagonal flow strict: `adapters -> application -> domain`, with `infrastructure` implementing domain ports. Use `domain/ports` for contracts, `application/requests`, `handlers`, and `use_cases` for orchestration, `adapters/api` and `adapters/mcp` for transport, and `infrastructure/odoo`, `agent`, `db`, and `runtime` for concrete backends. Tests mirror the code layout under `tests/unit`, `tests/integration`, and `tests/e2e`. Config files live in `config/`; local tooling and demos live in `scripts/`.

## Build, Test, and Development Commands
- `uv sync --extra dev`: install runtime and contributor tooling.
- `uv run sumampa_odoo_agent --reload`: run the FastAPI app locally on `127.0.0.1:8000`.
- `uv run sumampa_odoo_agent --mcp`: run the MCP server over stdio.
- `uv run pytest`: run the full test suite.
- `uv run pytest tests/unit` or `uv run pytest -m integration`: run a focused test slice.
- `uv run ruff check .`: run linting and import-order checks.
- `uv run mypy src tests`: run strict type checks.
- `docker compose -f docker-compose.odoo19.yml up -d`: start the local Odoo 19 integration stack.

## Coding Style & Naming Conventions
Use Python 3.11+, 4-space indentation, and explicit type hints. Ruff enforces a 100-character line length; mypy runs in strict mode. Prefer `snake_case` for modules/functions, `PascalCase` for classes, and request/handler names such as `CreateInvoiceCommand` and `CreateInvoiceCommandHandler`. Do not put Odoo logic in FastAPI routers or MCP tools; put it in handlers, ports, and infrastructure backends. Keep real Odoo writes explicit and auditable; defaults must remain `dry-run` for Odoo and `stub` for the agent. If enabling the Microsoft Agent Framework provider, keep imports lazy so startup still works without credentials.

## Testing Guidelines
Pytest discovers `test_*.py` files under `tests/`. Integration scenarios are marked with `@pytest.mark.integration`; keep using `tests/unit`, `tests/integration`, and `tests/e2e` to separate scope clearly. Add unit coverage for new application logic first, then integration tests for Odoo, OpenAI, Postgres, or Redis paths when behavior crosses a port boundary. Place reusable fixtures in `tests/integration/fixtures/`.

## Commit & Pull Request Guidelines
History follows Conventional Commits, for example `fix(chat): keep active invoice context` and `feat(demo): add one-shot command`. Use `type(scope): summary` when a scope helps. PRs should explain the user-visible change, note touched layers, list commands run, and call out config or payload changes. When adding or changing Odoo operations, keep API and MCP exposure aligned when appropriate and include example request payloads in the PR description.
