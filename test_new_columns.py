"""测试新增的列和列顺序"""

# 模拟一个简单的Trade对象来验证字段
class Trade:
    def __init__(self):
        self.code = "002364"
        self.name = "中恒电气"
        self.entry_date = "2025-01-07"
        self.exit_date = "2025-01-09"
        self.gross_pnl = 1962
        self.net_pnl = 1962.48
        self.net_pnl_pct = 0.0608
        self.open_change_pct = -0.0232  # 开盘跌幅-2.32%
        self.buy_price = 30.50
        self.buy_exec = 30.5153
        self.sell_price = 31.32
        self.sell_exec = 31.2868
        self.rank_t_minus_2 = None
        self.rank_t1 = 15
        self.rank_t = 8
        
    def to_dict(self):
        return {
            'code': self.code,
            'name': self.name,
            'entry_date': self.entry_date,
            'exit_date': self.exit_date,
            'rank_t_minus_2': self.rank_t_minus_2,
            'rank_t1': self.rank_t1,
            'rank_t': self.rank_t,
            'open_change_pct': self.open_change_pct,
            'buy_price': self.buy_price,
            'buy_exec': self.buy_exec,
            'sell_price': self.sell_price,
            'sell_exec': self.sell_exec,
            'gross_pnl': int(round(self.gross_pnl)),
            'net_pnl': self.net_pnl,
            'net_pnl_pct': self.net_pnl_pct
        }


# 测试字典输出
trade = Trade()
data = trade.to_dict()

print("Trade字段包含open_change_pct:", 'open_change_pct' in data)
print(f"open_change_pct值: {data['open_change_pct']:.2%}")

# 测试DataFrame列顺序
import pandas as pd

trades_df = pd.DataFrame([data])
cols = list(trades_df.columns)

# 模拟save_results的列顺序调整
priority_cols = ['code', 'name', 'entry_date', 'exit_date', 'gross_pnl', 'net_pnl', 'net_pnl_pct', 'open_change_pct',
               'buy_price', 'buy_exec', 'sell_price', 'sell_exec']
remaining_cols = [c for c in cols if c not in priority_cols]
new_order = [c for c in priority_cols if c in cols] + remaining_cols
trades_df = trades_df[new_order]

print("\n✅ 列顺序（前12列）:")
for i, col in enumerate(trades_df.columns[:12], 1):
    print(f"  {i}. {col}")

print(f"\n✅ buy_price和sell_price位置:")
buy_idx = list(trades_df.columns).index('buy_price')
sell_idx = list(trades_df.columns).index('sell_price')
print(f"  buy_price: 第{buy_idx+1}列")
print(f"  sell_price: 第{sell_idx+1}列")
print(f"  相邻度: {sell_idx - buy_idx} 列之差")

print(f"\n✅ 示例数据:")
print(trades_df[['code', 'name', 'open_change_pct', 'buy_price', 'sell_price', 'gross_pnl', 'net_pnl_pct']].to_string(index=False))
