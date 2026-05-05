"""
update_shares.py
批量拉取全市场总股本，写入 stocks.total_shares。

数据源：mootdx finance 接口（字段 zongguben）
多线程并发，默认 20 线程，约 5-10 分钟完成全量（5000只）。

Usage:
    python src/update_shares.py [--db data/quant.db] [--workers 20] [--force]
    
    --force   强制重新拉取（默认跳过已有数据）
"""

from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from quant_db import connect


def fetch_shares(code: str) -> tuple[str, float | None]:
    """拉取单只股票总股本，返回 (code, total_shares)。"""
    try:
        from mootdx.quotes import Quotes
        client = Quotes.factory(market='std', bestip=False)
        df = client.finance(symbol=code)
        if df is None or df.empty:
            return code, None
        val = df['zongguben'].iloc[0]
        return code, float(val) if val and val == val else None  # NaN check
    except Exception:
        return code, None


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Batch fetch total shares into stocks table")
    p.add_argument("--db", type=Path, default=PROJECT_ROOT / "data" / "quant.db")
    p.add_argument("--workers", type=int, default=20)
    p.add_argument("--force", action="store_true", help="Re-fetch even if already populated")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    conn = connect(args.db)

    all_codes = [
        r["code"] for r in conn.execute(
            "SELECT code FROM stocks ORDER BY code"
        )
    ]

    if not args.force:
        done = {
            r["code"] for r in conn.execute(
                "SELECT code FROM stocks WHERE total_shares IS NOT NULL"
            )
        }
        codes = [c for c in all_codes if c not in done]
    else:
        codes = all_codes

    total = len(codes)
    print(f"Total stocks: {len(all_codes)}  Already done: {len(all_codes)-total}  To fetch: {total}")
    if not total:
        print("Nothing to do.")
        return

    today = date.today().isoformat()
    ok = fail = 0
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(fetch_shares, code): code for code in codes}
        batch: list[tuple[str, float | None]] = []

        for i, future in enumerate(as_completed(futures), 1):
            code, shares = future.result()
            if shares is not None:
                ok += 1
                batch.append((shares, today, code))
            else:
                fail += 1

            # 每 100 条批量写库
            if len(batch) >= 100 or i == total:
                with conn:
                    conn.executemany(
                        "UPDATE stocks SET total_shares=?, shares_updated_at=? WHERE code=?",
                        batch,
                    )
                batch.clear()

            if i % 200 == 0 or i == total:
                elapsed = time.time() - t0
                speed = i / elapsed
                eta = (total - i) / speed if speed > 0 else 0
                print(
                    f"  [{i}/{total}] ok={ok} fail={fail} "
                    f"speed={speed:.1f}/s ETA={eta:.0f}s"
                )

    elapsed = time.time() - t0
    print(f"\nDone. ok={ok} fail={fail} elapsed={elapsed:.0f}s")

    # 汇总
    r = conn.execute("SELECT COUNT(*) n FROM stocks WHERE total_shares IS NOT NULL").fetchone()
    print(f"stocks with total_shares: {r['n']} / {len(all_codes)}")


if __name__ == "__main__":
    main()
