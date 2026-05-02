#!/usr/bin/env python3
"""Probe Xueqiu ranking API capacity and parameter boundaries."""

from __future__ import annotations

import json
import math
import os
from datetime import datetime
from pathlib import Path

import requests


PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = PROJECT_ROOT / "reports"
OUT_JSON = OUT_DIR / "xueqiu_capacity_probe.json"


def disable_proxy_env() -> None:
    for key in [
        "http_proxy",
        "https_proxy",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "all_proxy",
        "ALL_PROXY",
    ]:
        os.environ.pop(key, None)
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"


def fetch_count(order_by: str, extra: dict | None = None, size: int = 200) -> dict:
    url = "https://xueqiu.com/service/v5/stock/screener/screen"
    headers = {
        "Accept": "*/*",
        "Referer": "https://xueqiu.com/hq",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/100.0.4896.127 Safari/537.36"
        ),
        "X-Requested-With": "XMLHttpRequest",
    }
    params = {
        "category": "CN",
        "size": str(size),
        "order": "desc",
        "order_by": order_by,
        "only_count": "0",
        "page": "1",
    }
    if extra:
        params.update(extra)
    data = requests.get(url, params=params, headers=headers, timeout=20).json().get("data", {})
    items = data.get("list") or []
    count = data.get("count")
    return {
        "order_by": order_by,
        "size": size,
        "extra": extra or {},
        "count": count,
        "page1_len": len(items),
        "pages_at_200": math.ceil(count / 200) if isinstance(count, int) else None,
        "first_symbol": items[0].get("symbol") if items else None,
    }


def main() -> int:
    disable_proxy_env()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    order_bys = ["follow", "follow7d", "tweet", "deal"]
    normal = [fetch_count(ob) for ob in order_bys]
    page_size_test = [fetch_count("follow", size=s) for s in (50, 100, 200, 500, 1000)]
    history_param_test = [
        fetch_count("follow", extra={"date": "2025-01-02"}),
        fetch_count("follow", extra={"begin": "2025-01-02", "end": "2025-01-02"}),
    ]

    out = {
        "run_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "normal": normal,
        "page_size_test": page_size_test,
        "history_param_test": history_param_test,
    }
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"json={OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
