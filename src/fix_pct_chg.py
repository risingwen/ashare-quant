"""
修复 daily_bars 中 pct_chg=0 但实际有成交（amount>0）的记录。

策略：
1. 有前驱记录的：用 (close - prev_close) / prev_close * 100 重算
   - 只修复 close != prev_close 的（真正非平盘）
2. 无前驱记录的（首日上市新股）：从东财 K 线接口拉取
"""
import sqlite3
import sys
import time
import requests
from pathlib import Path

DB_PATH = Path('/data/quant_research/data/quant.db')

MARKET_SECID = {
    'Mainboard': lambda c: f"{'1' if c.startswith('6') else '0'}.{c}",
    'ChiNext':   lambda c: f"0.{c}",
    'STAR':      lambda c: f"1.{c}",
    'BSE':       lambda c: f"0.{c}",
}

def fetch_eastmoney_pct(secid: str, date: str) -> float | None:
    """从东财K线接口拉取指定日期的涨跌幅（f59字段）"""
    url = 'https://push2his.eastmoney.com/api/qt/stock/kline/get'
    params = {
        'secid': secid,
        'fields1': 'f1,f2,f3,f4,f5,f6',
        'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
        'klt': '101', 'fqt': '1',
        'ut': 'fa5fd1943c7b386f172d6893dbfba10b',
        'beg': date.replace('-', ''),
        'end': date.replace('-', ''),
        'lmt': '3',
    }
    try:
        r = requests.get(url, params=params, timeout=8)
        klines = r.json().get('data', {}).get('klines', [])
        for k in klines:
            parts = k.split(',')
            if parts[0] == date and len(parts) > 8:
                return float(parts[8])
    except Exception as e:
        print(f"  东财接口失败 {secid} {date}: {e}")
    return None


def fix(dry_run=False):
    conn = sqlite3.connect(str(DB_PATH), isolation_level=None)
    conn.row_factory = sqlite3.Row

    # 找出所有需修复候选：pct_chg=0 且 amount>0
    targets = conn.execute("""
        SELECT b.date, b.code, b.close, s.market
        FROM daily_bars b
        JOIN stocks s ON s.code = b.code
        WHERE b.pct_chg = 0 AND b.amount > 0 AND s.market != 'Other'
        ORDER BY b.date, b.code
    """).fetchall()

    print(f"候选记录数: {len(targets)}")

    fixed_calc = 0       # 用prev_close计算修复
    fixed_remote = 0     # 用东财接口修复（首日新股）
    skipped_flat = 0     # 真平盘（close==prev_close），不修
    skipped_no_data = 0  # 无前驱且东财也没有

    conn.execute("BEGIN")
    for i, row in enumerate(targets):
        date, code, close, market = row['date'], row['code'], row['close'], row['market']

        # 取前一交易日 close
        prev = conn.execute("""
            SELECT close FROM daily_bars
            WHERE code = ? AND date < ?
            ORDER BY date DESC LIMIT 1
        """, (code, date)).fetchone()

        if prev:
            prev_close = prev['close']
            if not prev_close or prev_close == 0:
                skipped_no_data += 1
                continue

            if abs(close - prev_close) < 1e-6:
                # close == prev_close，真正的平盘，pct=0 正确
                skipped_flat += 1
                continue

            pct = (close - prev_close) / prev_close * 100.0
            if not dry_run:
                conn.execute(
                    "UPDATE daily_bars SET pct_chg=? WHERE date=? AND code=?",
                    (pct, date, code)
                )
            fixed_calc += 1

        else:
            # 首日上市，无前驱，去东财拉
            secid_fn = MARKET_SECID.get(market)
            if not secid_fn:
                skipped_no_data += 1
                continue

            secid = secid_fn(code)
            pct = fetch_eastmoney_pct(secid, date)
            time.sleep(0.15)

            if pct is None:
                skipped_no_data += 1
                continue

            if abs(pct) < 1e-6:
                skipped_flat += 1
                continue

            if not dry_run:
                conn.execute(
                    "UPDATE daily_bars SET pct_chg=? WHERE date=? AND code=?",
                    (pct, date, code)
                )
            fixed_remote += 1
            if dry_run:
                print(f"  [DRY] 首日新股 {code} {date} pct={pct:.3f}%")

        if (i + 1) % 2000 == 0:
            if not dry_run:
                conn.execute("COMMIT")
                conn.execute("BEGIN")
            print(f"  进度 {i+1}/{len(targets)}: calc={fixed_calc} remote={fixed_remote} flat={skipped_flat} nodata={skipped_no_data}")

    if not dry_run:
        conn.execute("COMMIT")

    print(f"\n完成:")
    print(f"  修复(calc)   = {fixed_calc}")
    print(f"  修复(remote) = {fixed_remote}")
    print(f"  真平盘跳过   = {skipped_flat}")
    print(f"  无数据跳过   = {skipped_no_data}")


if __name__ == '__main__':
    dry_run = '--dry-run' in sys.argv
    if dry_run:
        print("[DRY RUN 模式，不写入DB]")
    fix(dry_run=dry_run)
