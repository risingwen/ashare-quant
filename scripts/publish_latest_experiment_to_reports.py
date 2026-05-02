#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Publish latest experiment markdown files into reports/ for GitHub Pages workflow."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXPERIMENTS_ROOT = PROJECT_ROOT / "data" / "experiments"
REPORTS_ROOT = PROJECT_ROOT / "reports"
GENERATED_ROOT = REPORTS_ROOT / "generated"


def find_latest_experiment() -> Path | None:
    if not EXPERIMENTS_ROOT.exists():
        return None
    exps = [p for p in EXPERIMENTS_ROOT.iterdir() if p.is_dir()]
    if not exps:
        return None
    exps.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return exps[0]


def copy_if_exists(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def main() -> int:
    latest = find_latest_experiment()
    GENERATED_ROOT.mkdir(parents=True, exist_ok=True)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines: list[str] = []
    lines.append("# 最新实验发布\n\n")
    lines.append(f"更新时间：{now}\n\n")

    if latest is None:
        lines.append("未发现 `data/experiments/` 下的实验目录。\n")
        (REPORTS_ROOT / "latest.md").write_text("".join(lines), encoding="utf-8")
        print("No experiment found. Updated reports/latest.md with notice.")
        return 0

    exp_id = latest.name
    src_reports = latest / "reports"
    lines.append(f"实验目录：`{exp_id}`\n\n")

    copied: list[tuple[str, str]] = []

    overview_src = src_reports / "overview.md"
    overview_dst = GENERATED_ROOT / f"{exp_id}_overview.md"
    if copy_if_exists(overview_src, overview_dst):
        copied.append(("实验总览", f"generated/{overview_dst.name}"))

    diagnosis_src = src_reports / "valid_diagnosis.md"
    diagnosis_dst = GENERATED_ROOT / f"{exp_id}_valid_diagnosis.md"
    if copy_if_exists(diagnosis_src, diagnosis_dst):
        copied.append(("验证诊断", f"generated/{diagnosis_dst.name}"))

    top_dir_src = src_reports / "top_details"
    top_index_dst = GENERATED_ROOT / f"{exp_id}_top_details_index.md"
    if top_dir_src.exists():
        detail_files = sorted(top_dir_src.glob("*.md"))
        if detail_files:
            idx_lines = [f"# Top Details - {exp_id}\n\n"]
            for f in detail_files:
                dst = GENERATED_ROOT / f"{exp_id}_{f.name}"
                copy_if_exists(f, dst)
                idx_lines.append(f"- [{f.name}](./{dst.name})\n")
            top_index_dst.write_text("".join(idx_lines), encoding="utf-8")
            copied.append(("Top明细", f"generated/{top_index_dst.name}"))

    if copied:
        lines.append("## 已发布文件\n\n")
        for title, rel in copied:
            lines.append(f"- [{title}](./{rel})\n")
    else:
        lines.append("未发现可发布的 md 文件（期待 `overview.md` / `valid_diagnosis.md` / `top_details/*.md`）。\n")

    (REPORTS_ROOT / "latest.md").write_text("".join(lines), encoding="utf-8")
    print(f"Published latest experiment from: {exp_id}")
    print(f"Updated: {REPORTS_ROOT / 'latest.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
