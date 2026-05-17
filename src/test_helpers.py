"""Shared helpers for repository-level diagnostic test scripts."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import List, Optional


def build_rise2_cmd(
    project_root: Path,
    *,
    hot_top_n: Optional[int] = None,
    max_positions: Optional[int] = None,
    per_trade_cash_frac: Optional[float] = None,
) -> List[str]:
    """Build a command for the hot-rank rise2 backtest script."""
    cmd = [
        sys.executable,
        str(project_root / "scripts" / "backtest_hot_rank_rise2_strategy.py"),
        "--config",
        str(project_root / "config" / "strategies" / "hot_rank_rise2.yaml"),
    ]
    if hot_top_n is not None:
        cmd.extend(["--param.hot_top_n", str(hot_top_n)])
    if max_positions is not None:
        cmd.extend(["--param.max_positions", str(max_positions)])
    if per_trade_cash_frac is not None:
        cmd.extend(["--param.per_trade_cash_frac", str(per_trade_cash_frac)])
    return cmd


def run_cmd_capture_tail(cmd: List[str], cwd: Path, tail_lines: int = 100) -> str:
    """Run a command and return the last lines of stdout."""
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=cwd,
    )
    lines = result.stdout.split("\n")
    return "\n".join(lines[-tail_lines:])
