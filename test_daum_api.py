import urllib.request
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

url = "https://finance.daum.net/api/quotes/A005930?summary=false"
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)', 'Referer': 'https://finance.daum.net/'})
data = json.loads(urllib.request.urlopen(req, timeout=5).read().decode('utf-8'))
for k, v in data.items():
    print(f"{k}: {v}")
