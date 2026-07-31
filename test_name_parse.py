import urllib.request
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

url = "https://finance.naver.com/item/main.naver?code=004870"
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
html_bytes = urllib.request.urlopen(req, timeout=5).read()

for enc in ['euc-kr', 'cp949', 'utf-8']:
    try:
        html = html_bytes.decode(enc)
        m = re.search(r'<title>(.*?)</title>', html)
        print(f"Encoding {enc} Title:", m.group(1) if m else "No match")
        m2 = re.search(r'<div class="wrap_company">\s*<h2>\s*<a[^>]*>(.*?)</a>', html)
        print(f"Encoding {enc} Name:", m2.group(1) if m2 else "No match")
    except Exception as e:
        print(f"Encoding {enc} Error:", e)
