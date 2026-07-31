import urllib.request
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

url = "https://finance.naver.com/item/main.naver?code=005930"
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
html = urllib.request.urlopen(req, timeout=5).read().decode('utf-8', errors='ignore')

open_m = re.search(r'sp_txt3">시가</span>.*?<span class="blind">([\d,]+)</span>', html, re.DOTALL)
high_m = re.search(r'sp_txt4">고가</span>.*?<span class="blind">([\d,]+)</span>', html, re.DOTALL)
low_m = re.search(r'sp_txt5">저가</span>.*?<span class="blind">([\d,]+)</span>', html, re.DOTALL)
vol_m = re.search(r'sp_txt9">거래량</span>.*?<span class="blind">([\d,]+)</span>', html, re.DOTALL)

per_m = re.search(r'id="_per"[^>]*>([\d,\.]+)</em>', html)
eps_m = re.search(r'id="_eps"[^>]*>([\d,\.]+) ceramic|id="_eps"[^>]*>([\d,\.]+)</em>', html)
pbr_m = re.search(r'id="_pbr"[^>]*>([\d,\.]+)</em>', html)
dvd_m = re.search(r'id="_dvr"[^>]*>([\d,\.]+)</em>', html)

print("시가:", open_m.group(1) if open_m else "None")
print("고가:", high_m.group(1) if high_m else "None")
print("저가:", low_m.group(1) if low_m else "None")
print("거래량:", vol_m.group(1) if vol_m else "None")

print("PER:", per_m.group(1) if per_m else "None")
print("PBR:", pbr_m.group(1) if pbr_m else "None")
print("DVD:", dvd_m.group(1) if dvd_m else "None")
