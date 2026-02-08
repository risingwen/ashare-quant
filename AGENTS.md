# AGENTS Guide for ashare-quant

This guide is for agentic coding tools operating in this repository.

## 1) Repository Snapshot

- Language: Python.
- Core dependencies: `akshare`, `pandas`, `pyarrow`, `duckdb`, `pyyaml`, `tqdm`, `pytest`.
- Key directories:
  - `src/`: shared utilities (`utils.py`, `validation.py`, `manifest.py`).
  - `scripts/`: CLI workflows for download, feature engineering, backtest, report generation.
  - `config/`: YAML configs (`data_config.yaml`, `backtest_base.yaml`, `strategies/*.yaml`).
  - Root: many `test_*.py` files used for pytest and diagnostics.

## 2) Environment Setup

Work from repo root (`ashare-quant`).

```bash
python -m venv .venv
source .venv/bin/activate            # Linux/macOS
# .venv\Scripts\activate            # Windows
pip install -r requirements.txt
```

If needed: `cp config.example.yaml config.yaml`

## 3) Build / Lint / Test Commands

There is no package build system configured (`pyproject.toml` absent).

### 3.1 Pipeline commands

```bash
# Environment + dependency sanity check
python test_system.py

# Incremental update
python scripts/update_daily_incremental.py --config config.yaml

# Feature engineering
python scripts/prepare_features.py --config config/data_config.yaml

# Main backtest
python scripts/backtest_hot_rank_strategy.py --config config/strategies/hot_rank_drop7.yaml
```

### 3.2 Lint/static checks

No dedicated formatter/linter config is present (no ruff/black/isort config files found).

```bash
# Syntax validation
python -m compileall src scripts

# Optional quick test discovery check
pytest --collect-only -q
```

### 3.3 Test commands (including single test)

README mentions `pytest tests/`, but tests are currently mostly root-level `test_*.py`.

```bash
# All pytest tests
pytest -q

# One test file
pytest -q test_system.py

# One specific test function
pytest -q test_system.py::test_akshare_connection

# Subset by keyword
pytest -q -k hot_rank

# Script-style diagnostics
python test_hot_rank.py
```

Notes:
- Some tests hit live AkShare endpoints; failures can be network/data-source related.

## 4) Code Style Guidelines

Follow patterns used in `src/` and `scripts/`.

### 4.1 Imports and module layout

- Import order: stdlib -> third-party -> local modules.
- Prefer explicit imports; avoid wildcard imports.
- Keep script module docstring with purpose and usage example.
- Existing scripts commonly set paths via:
  - `PROJECT_ROOT = Path(__file__).parent.parent`
  - `sys.path.insert(0, str(PROJECT_ROOT))` or `... / "src"`
  Keep this pattern unless doing a full packaging refactor.

### 4.2 Formatting and structure

- Follow PEP 8 (4 spaces, clear naming, readable line length).
- Use `argparse` for runnable scripts.
- Script entrypoint pattern is expected:
  - `def main(): ...`
  - `if __name__ == "__main__": main()`

### 4.3 Types and schemas

- Add type hints to public functions/methods where practical.
- Use standard typing consistently (`Optional`, `Dict`, `List`, `Tuple`).
- Document DataFrame input/output columns in docstrings.
- Keep normalized field names in `snake_case` (`date`, `code`, `open`, `high`, `low`, `close`, etc.).

### 4.4 Naming conventions

- `snake_case`: functions, variables, config keys, DataFrame columns.
- `PascalCase`: classes.
- Strategy metadata from YAML (`strategy.name`, `strategy.version`) drives output filenames.
- Prefer descriptive names over short abbreviations.

### 4.5 Error handling and logging

- Use `logging` for operational paths; avoid excessive `print` in production code.
- Handle exceptions at API/file boundaries with clear context.
- Reuse retry/rate-limit helpers from `src/utils.py`.
- Keep workflows resumable through manifest updates (`src/manifest.py`).

## 5) Data and File Hygiene

- Do not commit large generated artifacts under `data/`.
- Respect `.gitignore` exclusions (`data/parquet/`, `logs/`, local DB/CSV/JSON outputs).
- Keep code changes separate from generated data outputs unless explicitly requested.

## 6) Cursor and Copilot Rules

### 6.1 Copilot instructions present

Source: `.github/copilot-instructions.md`

Agents must incorporate these requirements:
- Project objective: fetch A-share daily data via AkShare and analyze with DuckDB on Parquet.
- Default data scope: trading-day daily data, A-share universe, normalized `snake_case` fields.
- Engineering requirements:
  - scripts should have clear script identity, `main()`, and argparse parameters;
  - use logging; key step messages should be clear English and avoid emoji;
  - implement resumable runs, retry, rate limiting, and validation (rows/duplicates/nulls/date continuity);
  - keep structure clear (`src/`, `tests/`, `data/`).
- Commit message preference: concise Chinese commit messages explaining change and reason.
- Strategy docs in `.github/prompts/` should include logic, parameters, implementation points.
- Strategy logic/parameter changes should append Changelog entries:
  - `date + category (Changed/Fixed/Added/Removed) + reason + impact`.

### 6.2 Cursor rules status

- `.cursorrules`: not found.
- `.cursor/rules/`: not found.

Keep this file updated when commands, tooling, or repository rules change.
