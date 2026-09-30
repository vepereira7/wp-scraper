# Repository guidance

This is a standalone Python project, separate from the WP Stats application.

## Boundaries

- Do not mix WP Stats application code into this repository.
- Do not implement integration with WP Stats without explicit instructions.
- Do not perform real scraping without fixtures and tests.
- Do not add dependencies without a clear justification.
- Do not commit `.env`, `.venv`, temporary files, generated outputs, or sensitive data.
- Do not commit, push, tag, deploy, or change branches.

## Development conventions

- Use Python 3.11 or newer.
- Use `uv` to run project commands.
- Use pytest for tests and ruff for linting.
- Keep models in `src/waterpolo/models/`.
- Keep fetching, scraping, and parsing code in `src/waterpolo/scraper/`.
- Keep output and exporter code in `src/waterpolo/services/`.
- Keep project documentation in `docs/`.

## Useful commands

```console
uv run pytest
uv run ruff check .
uv run python -m waterpolo.main
```
