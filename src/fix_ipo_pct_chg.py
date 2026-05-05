"""
修复新股首日上市 pct_chg=0 的记录。
仅针对"非起始日、无前驱记录、pct_chg=0、amount>0"的新股首日。
从东财历史K线接口拉取实际涨跌幅并写入 DB。
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

def fetch_pct(secid: str, date: str) -> float | None:
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
        print(f"  ERR {secid} {date}: {e}")
    return None


def main(dry_run=False):
    conn = sqlite3.connect(str(DB_PATH), isolation_level=None)
    conn.row_factory = sqlite3.Row

    # 全量交易日顺序，构建前一交易日映射
    dates = [r[0] for r in conn.execute(
        'SELECT DISTINCT date FROM daily_bars ORDER BY date').fetchall()]
    date_prev = {dates[i]: dates[i-1] for i in range(1, len(dates))}
    first_date = dates[0]

    # 找出所有候选
    candidates = conn.execute("""
        SELECT b.date, b.code, b.close, s.market, s.name
        FROM daily_bars b JOIN stocks s ON s.code=b.code
        WHERE b.pct_chg=0 AND b.amount>0 AND s.market!='Other'
        ORDER BY b.date, b.code
    """).fetchall()

    # 筛选真正的首日新股
    targets = []
    for row in candidates:
        date, code = row['date'], row['code']
        if date == first_date:
            continue
        prev_date = date_prev.get(date)
        if not prev_date:
            continue
        prev_row = conn.execute(
            'SELECT close FROM daily_bars WHERE code=? AND date=?',
            (code, prev_date)).fetchone()
        if not prev_row:
            targets.append(row)

    print(f"首日新股待修复: {len(targets)} 条")

    fixed = 0
    skipped_flat = 0
    skipped_nodata = 0

    conn.execute("BEGIN")
    for i, row in enumerate(targets):
        date, code, close, market, name = (
            row['date'], row['code'], row['close'], row['market'], row['name'])

        secid_fn = MARKET_SECID.get(market)
        if not secid_fn:
            skipped_nodata += 1
            continue

        secid = secid_fn(code)
        pct = fetch_pct(secid, date)
        time.sleep(0.2)

        if pct is None:
            print(f"  [{i+1}/{len(targets)}] {code} {name} {date} 无数据，跳过")
            skipped_nodata += 1
            continue

        if abs(pct) < 1e-6:
            print(f"  [{i+1}/{len(targets)}] {code} {name} {date} pct=0 确认平盘，跳过")
            skipped_flat += 1
            continue

        print(f"  [{i+1}/{len(targets)}] {code} {name} {date} pct={pct:.2f}% {'[DRY]' if dry_run else '写入'}")
        if not dry_run:
            conn.execute(
                "UPDATE daily_bars SET pct_chg=? WHERE date=? AND code=?",
                (pct, date, code))
        fixed += 1

        if (i + 1) % 50 == 0 and not dry_run:
            conn.execute("COMMIT")
            conn.execute("BEGIN")

    if not dry_run:
        conn.execute("COMMIT")

    print(f"\n完成: 修复={fixed} 平盘跳过={skipped_flat} 无数据跳过={skipped_nodata}")


if __name__ == '__main__':
    dry_run = '--dry-run' in sys.argv
    if dry_run:
        print("[DRY RUN]")
    main(dry_run=dry_run)
