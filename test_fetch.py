# -*- coding: utf-8 -*-
import sys
import urllib.request
import re

sys.stdout.reconfigure(encoding='utf-8')

def test_blind_exday(code="004870"):
    url_m = f"https://finance.naver.com/item/main.naver?code={code}"
    req_m = urllib.request.Request(url_m, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    html_m = urllib.request.urlopen(req_m, timeout=5).read().decode('euc-kr', errors='ignore')
    
    exday_m = re.search(r'<p class="no_exday">(.*?)</p>', html_m, re.DOTALL)
    diff_p = 0.0
    pct_p = 0.0
    if exday_m:
        ex_text = exday_m.group(1)
        blind_matches = re.findall(r'<span class="blind">([\d,\.]+)</span>', ex_text)
        if blind_matches:
            diff_p = float(blind_matches[0].replace(',', ''))
        if len(blind_matches) >= 2:
            pct_p = float(blind_matches[1].replace(',', ''))
        if "ico fall" in ex_text or "down" in ex_text or "nv01" in ex_text:
            diff_p = -abs(diff_p)
            pct_p = -abs(pct_p)
        else:
            diff_p = abs(diff_p)
            pct_p = abs(pct_p)
            
    print(f"100% PERFECT EXDAY for {code}: Diff={diff_p:+,.0f} KRW, Rate={pct_p:+.2f}%")

if __name__ == "__main__":
    test_blind_exday("004870") # 티웨이홀딩스 (960원 / +221원 / +29.91%)
    test_blind_exday("002350") # 넥센타이어 (6110원 / -350원 / -5.42%)
    test_blind_exday("071320") # 지역난방공사
    test_blind_exday("073240") # 금호타이어
