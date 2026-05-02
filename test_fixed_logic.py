"""测试修正后的匹配逻辑"""
test_codes = [
    '300001',  # 创业板
    '301038',  # 创业板
    '309999',  # 创业板
    '688001',  # 科创板
    '688999',  # 科创板
    '000001',  # 深市主板
    '600000',  # 沪市主板
    '002001',  # 深市中小板
]

print('修正后的判断逻辑测试:')
print('='*60)
for code in test_codes:
    if code.startswith('30') or code.startswith('688'):
        trigger = '-13%'
        board = '创业板' if code.startswith('30') else '科创板'
    else:
        trigger = '-7%'
        board = '主板/中小板'
    print(f'{code}: {board:12s} -> {trigger}')
