import urllib.request
import urllib.parse
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

for enc in ['utf-8', 'euc-kr']:
    encoded = urllib.parse.quote("CJ CGV".encode(enc))
    url_s = f"https://finance.naver.com/search/search.naver?query={encoded}"
    req_s = urllib.request.Request(url_s, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    html = urllib.request.urlopen(req_s, timeout=5).read().decode('euc-kr', errors='ignore')
    matches = re.findall(r'/item/main\.naver\?code=(\d+)', html)
    print(f"Encoding {enc} matches:", set(matches))
