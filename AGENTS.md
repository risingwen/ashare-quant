# Repository Guidelines

## Project Structure & Module Organization

This is a Python A-share quant research project. Core application code lives in `src/`, including SQLite data updates, report generation, screeners, health checks, and shared database utilities. Reusable CLI workflows and research/backtest scripts live in `scripts/`. Configuration files are in `config/`, with strategy YAMLs under `config/strategies/`. Tests live in `tests/`; live data-source checks are under `tests/integration/`. Generated artifacts belong in `data/`, `reports/`, and `logs/` and should not be committed unless explicitly requested. Legacy diagnostics and archived experiments are under `archive/`.

## Build, Test, and Development Commands

Run commands from the repository root:

```bash
pip install -r requirements.txt
python -m compileall src scripts
pytest -q
pytest -q -m "integration and network"
python src/update_sqlite_data.py --db data/quant.db --daily-source sina --workers 4
python src/generate_report.py --db data/quant.db --report-dir reports --start-date 2025-01-01
```

`compileall` validates syntax, `pytest` runs the test suite, the integration marker hits live AkShare/network endpoints, `update_sqlite_data.py` refreshes SQLite market data, and `generate_report.py` rebuilds static reports.

## Coding Style & Naming Conventions

Follow PEP 8 with 4-space indentation and descriptive names. Use `snake_case` for functions, variables, config keys, and DataFrame columns; use `PascalCase` for classes. Keep imports ordered as stdlib, third-party, then local modules. Runnable scripts should use `argparse`, include a short module docstring, and expose `main()` behind `if __name__ == "__main__":`. Prefer `logging` for operational code and clear exception context at API, filesystem, and database boundaries.

## Testing Guidelines

Use pytest. Name test files `test_*.py` and test functions `test_*`. Prefer deterministic unit tests for business logic and isolate network-dependent checks with the `integration` and `network` markers. Before submitting, run targeted tests for touched code plus `python -m compileall src scripts`. Treat live AkShare failures as potentially external; document them if they block validation.

## Commit & Pull Request Guidelines

Use concise Chinese commit messages that explain the change and reason, for example `增强数据完备性审计并统一报告风格`. Pull requests should describe what changed, why it changed, user/developer impact, and validation commands. Include screenshots or generated page paths for UI/report changes. Keep generated data out of PRs unless it is the requested deliverable.

## Security & Configuration Tips

Do not commit local databases, secrets, logs, or large generated outputs. Use `config.example.yaml` as the template for local configuration. Production-style paths assume `/data/quant_research`, but code should prefer configurable `--db`, `--report-dir`, and YAML options where available.
