import sys
sys.stdout.reconfigure(encoding='utf-8')
import bitemporal_engine

engine = bitemporal_engine.BitemporalEngine()

for q in ["CJ CGV", "카카오페이", "079160", "004870"]:
    ticker, name, info = engine.fetch_and_update_naver_realtime(q)
    print(f"\nQuery: '{q}' -> Ticker: {ticker}, Name: {name}, Price: {info['base_price']:,.0f}원, Pct: {info['pct_change']:+.2f}%, Diff: {info['diff_price']:+,.0f}원")
