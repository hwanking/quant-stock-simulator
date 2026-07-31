import urllib.request
import json
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

def test_fetch_stock(code):
    url_d = f"https://finance.daum.net/api/quotes/A{code}?summary=false"
    req_d = urllib.request.Request(url_d, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.daum.net/'})
    data = json.loads(urllib.request.urlopen(req_d, timeout=5).read().decode('utf-8'))
    
    print(f"\n=== Stock {code} ({data.get('name')}) ===")
    print("Price:", data.get('tradePrice'))
    print("Open:", data.get('openingPrice'))
    print("High:", data.get('highPrice'))
    print("Low:", data.get('lowPrice'))
    print("Volume:", data.get('accTradeVolume'))
    print("PER:", data.get('per'))
    print("PBR:", data.get('pbr'))
    print("EPS:", data.get('eps'))
    print("BPS:", data.get('bps'))
    print("DPS:", data.get('dps'))
    print("DebtRatio:", data.get('debtRatio'))

for c in ["005930", "000660", "004870", "071320"]:
    test_fetch_stock(c)
