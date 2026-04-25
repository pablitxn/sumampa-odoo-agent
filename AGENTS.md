# Repository Guidelines

## Project Structure & Module Organization
Code lives under `src/sumampa_odoo_agent`. Keep the structure simple: `api` for FastAPI transport, `services` for orchestration and business rules, and `integrations` for concrete backends such as Odoo, OpenAI extraction, agent runtime, and session storage. Shared schemas and workflow models should live under `services`, not in routers. Tests live under `tests/unit`, `tests/integration`, and `tests/e2e`. Local tooling and helper scripts live in `scripts/`.

## Build, Test, and Development Commands
- `uv sync --extra dev`: install runtime and contributor tooling.
- `uv run sumampa_odoo_agent --reload`: run the FastAPI app locally on `127.0.0.1:8000`.
- `uv run pytest`: run the full test suite.
- `uv run pytest tests/unit` or `uv run pytest -m integration`: run a focused test slice.
- `uv run ruff check .`: run linting and import-order checks.
- `uv run mypy src tests`: run strict type checks.
- `docker compose --profile odoo up -d odoo19`: start the local Odoo 19 integration stack.

## Coding Style & Naming Conventions
Use Python 3.11+, 4-space indentation, and explicit type hints. Ruff enforces a 100-character line length; mypy runs in strict mode. Prefer `snake_case` for modules/functions and `PascalCase` for classes. Do not put Odoo logic in FastAPI routers; keep orchestration in `services` and provider-specific behavior in `integrations`. Keep real Odoo writes explicit and auditable; defaults must remain `dry-run` for Odoo. If enabling the Microsoft Agent Framework provider, keep imports lazy so startup still works without credentials.

## Testing Guidelines
Pytest discovers `test_*.py` files under `tests/`. Integration scenarios are marked with `@pytest.mark.integration`; keep using `tests/unit`, `tests/integration`, and `tests/e2e` to separate scope clearly. Add unit coverage for new service logic first, then integration tests for Odoo, OpenAI, Postgres, or Redis paths when behavior crosses an integration boundary. Place reusable fixtures in `tests/integration/fixtures/`.

## Commit & Pull Request Guidelines
History follows Conventional Commits, for example `fix(chat): keep active invoice context` and `feat(api): simplify message payload`. Use `type(scope): summary` when a scope helps. PRs should explain the user-visible change, note touched layers, list commands run, and call out config or payload changes. When adding or changing Odoo operations, include example request payloads in the PR description.
