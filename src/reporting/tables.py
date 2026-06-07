"""Reusable HTML and Markdown table renderers."""

from __future__ import annotations

import html

from reporting.formatters import fmt_num, fmt_pct, format_table_cell


def simple_table(rows: list[dict[str, object]], columns: list[tuple[str, str]], limit: int | None = None) -> str:
    selected = rows[:limit] if limit else rows
    if not selected:
        return "<p class='empty'>暂无数据</p>"
    head = "".join(f"<th>{html.escape(label)}</th>" for _key, label in columns)
    body_rows = []
    for row in selected:
        cells = []
        for key, _label in columns:
            text = format_table_cell(key, row.get(key))
            cells.append(f"<td>{html.escape(text)}</td>")
        body_rows.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


def markdown_table(rows: list[dict[str, object]], columns: list[tuple[str, str]], limit: int | None = None) -> str:
    selected = rows[:limit] if limit else rows
    if not selected:
        return "No data.\n"
    lines = ["| " + " | ".join(label for _key, label in columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for row in selected:
        values = []
        for key, _label in columns:
            value = row.get(key)
            values.append(fmt_pct(value) if key.endswith("_rate") else fmt_num(value))
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines) + "\n"
