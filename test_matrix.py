import sys
sys.stdout.reconfigure(encoding='utf-8')
import bitemporal_engine

engine = bitemporal_engine.BitemporalEngine()
price, status, matrix = engine.get_realtime_stock_price_triple_check("005930.KS")
print("STATUS:", status)
for row in matrix:
    print(row)
