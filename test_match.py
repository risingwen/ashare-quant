"""测试字符串匹配"""
code = '301038'
print(f'Code: {code}')
print(f'Starts with 300: {code.startswith("300")}')
print(f'Starts with 301: {code.startswith("301")}')
print(f'Starts with 688: {code.startswith("688")}')
print(f'Match 300 or 688: {code.startswith("300") or code.startswith("688")}')
