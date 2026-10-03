#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
彩票開獎資料抓取程式 update.py（GitHub Actions 版）
====================================================
用途：
  定時抓取「無法由前端即時取得」的彩種開獎號碼，寫入 data/snapshot.json，
  供網站 index.html 讀取並顯示「資料更新時間」。

核心設計（三個重點）
--------------------
1. 期別比對：以「期別（period / issue）」判斷新舊。
   - 期別比快照新  -> 寫入新資料，status = "updated"
   - 期別與快照相同 -> 不重複寫入，status = "unchanged"
2. 失敗不覆蓋：抓取失敗或官網掛掉時，保留上一次成功資料，
   並標記 status = "delayed"、delayed = true（網站會顯示「資料延遲」）。
3. 逾時保護 + 單一彩種隔離：每個彩種獨立 try/except，
   任何一個彩種失敗都不影響其他彩種。

資料來源（皆經實測，HTTP 200）
------------------------------
  1. 中國福彩 3D      -> 500.com 公開 XML  (kaijiang.500.com/static/info/kaijiang/xml/sd/list.xml)
  2. 中國體彩 排列3   -> 500.com 公開 XML  (.../xml/pls/list.xml)
  3. 中國體彩 排列5   -> 500.com 公開 XML  (.../xml/plw/list.xml)
  4. 香港六合彩       -> 香港賽馬會官網 (bet.hkjc.com/ch/marksix/results)，JS 動態渲染，需無頭瀏覽器
  5. 台灣 BINGO BINGO -> 台灣彩券官方 API (api.taiwanlottery.com/TLCAPIWeB/Lottery/BingoResult)

注意：
  - 中國福彩/體彩「官方」端點 (cwl.gov.cn / sporttery.cn) 具反爬蟲保護 (HTTP 403/567)，
    故改用 500.com 公開 XML（內容為官方開獎結果之公開轉載）。
  - 香港六合彩官方 GraphQL 端點具白名單限制 (WHITELIST_ERROR)，故以無頭瀏覽器渲染官網取得。
  - 澳門六合彩：經查證澳門特區政府、DICJ 與司警局均明確表示「從未批准任何公司經營澳門六合彩」，
    所有以「澳門六合彩」名義之網站均屬虛假及非法。基於來源非法，本程式「不抓取」任何相關號碼。

執行方式
--------
  python3 update.py            # 依窗口判斷是否輪詢；窗口外僅檢查、不抓取
  python3 update.py --force    # 忽略窗口，立即抓取一次（手動補抓用）
  python3 update.py --print    # 只印出結果，不寫檔
  python3 update.py --status   # 只印出目前快照狀態

【要修改的地方】
  - 想調整開獎窗口（時間/星期）-> 修改下方 WINDOWS 字典
  - 想新增/移除彩種            -> 修改下方 FETCHERS 字典與對應 fetch_* 函式
  - 想改輸出檔路徑              -> 修改下方 OUT_FILE
"""

import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone, timedelta

# ===========================================================================
# 基本設定
# ===========================================================================
TZ = timezone(timedelta(hours=8))  # 台北 / 香港 / 上海 皆為 UTC+8
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# 輸出檔：與 index.html 同層的 data/snapshot.json
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
OUT_FILE = os.path.join(OUT_DIR, "snapshot.json")

# ---------------------------------------------------------------------------
# 開獎窗口設定（台北時間 UTC+8）
#   days     : 開獎日（0=週一 … 6=週日）
#   start/end: 窗口起訖（HH:MM），窗口內才輪詢
#   interval : 建議輪詢間隔（分鐘），僅供文件參考；實際由 cron 控制
# ---------------------------------------------------------------------------
WINDOWS = {
    "fc3d":  {"name": "中國福彩 3D",   "days": [0, 1, 2, 3, 4, 5, 6], "start": "20:30", "end": "22:30", "interval": 12},
    "pl3":   {"name": "中國體彩 排列3", "days": [0, 1, 2, 3, 4, 5, 6], "start": "20:30", "end": "22:30", "interval": 12},
    "pl5":   {"name": "中國體彩 排列5", "days": [0, 1, 2, 3, 4, 5, 6], "start": "20:30", "end": "22:30", "interval": 12},
    "hkjc":  {"name": "香港六合彩",     "days": [1, 3, 6],            "start": "21:00", "end": "23:00", "interval": 12},
    "bingo": {"name": "BINGO BINGO",   "days": [0, 1, 2, 3, 4, 5, 6], "start": "07:00", "end": "23:00", "interval": 10},
}


# ===========================================================================
# 工具函式
# ===========================================================================
def http_get(url, timeout=25):
    """發送 HTTP GET，回傳解碼後的字串。逾時預設 25 秒。"""
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _hm_to_min(hm):
    """'HH:MM' -> 當日分鐘數。"""
    h, m = hm.split(":")
    return int(h) * 60 + int(m)


def in_window(key, now):
    """回傳 (是否在窗口內, 窗口說明字串)。"""
    w = WINDOWS.get(key)
    if not w:
        return True, ""
    desc = "週%s %s–%s" % (
        "".join("一二三四五六日"[d] for d in w["days"]),
        w["start"], w["end"])
    if now.weekday() not in w["days"]:
        return False, desc
    cur = now.hour * 60 + now.minute
    return (_hm_to_min(w["start"]) <= cur <= _hm_to_min(w["end"])), desc


# ===========================================================================
# 1-3. 中國福彩3D / 體彩排列3 / 排列5  (500.com 公開 XML)
# ===========================================================================
XML_FEEDS = {
    "fc3d": ("https://kaijiang.500.com/static/info/kaijiang/xml/sd/list.xml",  "中國福彩 3D",   "福彩3D"),
    "pl3":  ("https://kaijiang.500.com/static/info/kaijiang/xml/pls/list.xml", "中國體彩 排列3", "排列3"),
    "pl5":  ("https://kaijiang.500.com/static/info/kaijiang/xml/plw/list.xml", "中國體彩 排列5", "排列5"),
}


def fetch_500xml(key):
    """抓取 500.com 公開 XML，解析最新一期（第一筆 <row>）。"""
    url, name, short = XML_FEEDS[key]
    xml = http_get(url)
    m = re.search(r'<row\s+([^>]+?)/>', xml)
    if not m:
        raise ValueError("no <row> found")
    attrs = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
    numbers = [int(x) for x in attrs.get("opencode", "").split(",") if x.strip() != ""]
    return {
        "name": name,
        "short": short,
        "period": attrs.get("expect", ""),
        "date": (attrs.get("opentime", "") or "")[:10],
        "time": (attrs.get("opentime", "") or "")[11:16],
        "numbers": numbers,
        "source": "500.com 公開 XML（官方開獎結果轉載）",
        "sourceUrl": url,
        "method": "需定時抓取（後端排程）",
    }


# ===========================================================================
# 4. 香港六合彩 (HKJC 官網，JS 動態渲染 -> 無頭瀏覽器)
# ===========================================================================
def fetch_hkjc():
    """以 Playwright 無頭瀏覽器渲染 HKJC 官網，解析期別與 7 個號碼。"""
    from playwright.sync_api import sync_playwright

    url = "https://bet.hkjc.com/ch/marksix/results"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(user_agent=UA, locale="zh-HK")
        page.goto(url, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(4000)
        html = page.content()
        browser.close()

    period_m = re.search(r'(\d{2}/\d{3})(?!\d)', html)
    if not period_m:
        raise ValueError("HKJC: 無法解析期別")
    period = period_m.group(1)
    after = html[period_m.end():]

    date_m = re.search(r'(\d{2}/\d{2}/\d{4})', after)
    date_iso = ""
    if date_m:
        d, mo, y = date_m.group(1).split("/")
        date_iso = "%s-%s-%s" % (y, mo, d)

    nums = re.findall(r'marksix-(\d+)\.', after)
    seen, ordered = set(), []
    for n in nums:
        if n not in seen:
            seen.add(n)
            ordered.append(int(n))
        if len(ordered) >= 7:
            break
    if len(ordered) < 7:
        raise ValueError("HKJC: 無法解析 7 個號碼 (got %d)" % len(ordered))

    return {
        "name": "香港六合彩",
        "short": "六合彩",
        "period": period,
        "date": date_iso,
        "time": "21:30",
        "numbers": ordered[:6],
        "special": ordered[6],
        "source": "香港賽馬會 HKJC 官網（無頭瀏覽器渲染）",
        "sourceUrl": url,
        "method": "需定時抓取（無頭瀏覽器）",
    }


# ===========================================================================
# 5. 台灣 BINGO BINGO 賓果賓果 (台灣彩券官方 API)
# ===========================================================================
def fetch_bingo():
    """抓取台彩官方 API，取當日最新一期。"""
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    url = ("https://api.taiwanlottery.com/TLCAPIWeB/Lottery/BingoResult"
           "?openDate=%s&pageNum=1&pageSize=200" % today)
    data = json.loads(http_get(url))
    rows = data.get("content", {}).get("bingoQueryResult", [])
    if not rows:
        raise ValueError("bingo: no rows for %s" % today)
    latest = max(rows, key=lambda x: x.get("drawTerm", 0))
    nums = [int(n) for n in latest.get("bigShowOrder", [])]
    return {
        "name": "BINGO BINGO 賓果賓果",
        "short": "賓果賓果",
        "period": str(latest.get("drawTerm", "")),
        "date": today,
        "time": "",
        "numbers": nums,
        "bullEye": latest.get("bullEyeTop"),
        "source": "台灣彩券官方 API（BingoResult）",
        "sourceUrl": "https://api.taiwanlottery.com/TLCAPIWeB/Lottery/BingoResult",
        "method": "自動抓取（前端即時）",
    }


# 彩種 -> 抓取函式對應表（要新增彩種就在這裡加一行）
FETCHERS = {
    "fc3d":  lambda: fetch_500xml("fc3d"),
    "pl3":   lambda: fetch_500xml("pl3"),
    "pl5":   lambda: fetch_500xml("pl5"),
    "hkjc":  fetch_hkjc,
    "bingo": fetch_bingo,
}


# ===========================================================================
# 快照讀寫
# ===========================================================================
def load_old():
    """讀取既有快照；不存在或損毀則回傳 None。"""
    try:
        with open(OUT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def main():
    now = datetime.now(TZ)
    force = "--force" in sys.argv
    old = load_old() or {}
    old_games = old.get("games", {}) or {}
    old_updated = old.get("updatedDisplay", "")

    snapshot = {
        "updated": now.isoformat(),
        "updatedDisplay": now.strftime("%Y/%m/%d %H:%M:%S"),
        "games": {},
        "status": {},
        "errors": [],
    }

    for key, fn in FETCHERS.items():
        win_ok, win_desc = in_window(key, now)
        prev = old_games.get(key)
        prev_period = (prev or {}).get("period")

        entry = {
            "window": win_desc,
            "lastAttempt": now.strftime("%Y/%m/%d %H:%M:%S"),
        }

        # --- 窗口外且非強制：不抓取，保留舊資料 ---
        if not win_ok and not force:
            if prev:
                entry.update(prev)
                entry["status"] = "outside_window"
                entry["delayed"] = bool(prev.get("delayed"))
                entry["lastSuccess"] = prev.get("lastSuccess") or old_updated
                snapshot["games"][key] = entry
                print("[SKIP] %-6s 窗口外（%s），保留上次資料 期別=%s" % (key, win_desc, prev_period))
            else:
                entry["status"] = "outside_window"
                entry["delayed"] = False
                snapshot["status"][key] = entry
                print("[SKIP] %-6s 窗口外（%s），尚無資料" % (key, win_desc))
            continue

        # --- 窗口內（或 --force）：嘗試抓取 ---
        try:
            fresh = fn()
            new_period = str(fresh.get("period", ""))

            if prev and prev_period and new_period and str(prev_period) == new_period:
                # 期別相同 -> 不重複寫入
                entry.update(prev)
                entry["status"] = "unchanged"
                entry["delayed"] = False
                entry["lastSuccess"] = prev.get("lastSuccess") or old_updated
                snapshot["games"][key] = entry
                print("[SAME] %-6s 期別未變（%s），跳過寫入" % (key, new_period))
            else:
                # 期別更新 -> 寫入新資料
                fresh["status"] = "updated"
                fresh["delayed"] = False
                fresh["lastAttempt"] = entry["lastAttempt"]
                fresh["lastSuccess"] = entry["lastAttempt"]
                fresh["window"] = win_desc
                snapshot["games"][key] = fresh
                print("[OK]   %-6s 期別更新 %s -> %s" % (key, prev_period or "(無)", new_period))

        except Exception as e:  # noqa: BLE001
            # 抓取失敗 -> 絕不覆蓋舊快照
            snapshot["errors"].append({"key": key, "error": str(e), "at": entry["lastAttempt"]})
            if prev:
                entry.update(prev)
                entry["status"] = "delayed"
                entry["delayed"] = True
                entry["lastSuccess"] = prev.get("lastSuccess") or old_updated
                entry["lastError"] = str(e)
                snapshot["games"][key] = entry
                print("[FAIL] %-6s %s -> 保留上次成功資料（標記延遲）" % (key, e))
            else:
                entry["status"] = "pending"
                entry["delayed"] = True
                entry["lastError"] = str(e)
                snapshot["status"][key] = entry
                print("[FAIL] %-6s %s -> 尚無可保留資料（標記延遲中）" % (key, e))

    # --- 窗口已結束但仍無新期別者 -> 標記「今日尚未開獎／延遲中」 ---
    for key, entry in list(snapshot["games"].items()):
        w = WINDOWS.get(key, {})
        if not w:
            continue
        end_min = _hm_to_min(w["end"])
        cur = now.hour * 60 + now.minute
        if now.weekday() in w["days"] and cur > end_min and entry.get("status") in ("unchanged", "outside_window"):
            entry["status"] = "pending"
            entry["delayed"] = True
            print("[WAIT] %-6s 窗口已結束仍無新期別 -> 標記延遲中" % key)

    if "--print" in sys.argv:
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
        return

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    print("寫入 %s（更新 %d / 延遲 %d / 錯誤 %d）" % (
        OUT_FILE,
        sum(1 for g in snapshot["games"].values() if g.get("status") == "updated"),
        sum(1 for g in snapshot["games"].values() if g.get("delayed")),
        len(snapshot["errors"])))


if __name__ == "__main__":
    if "--status" in sys.argv:
        print(json.dumps(load_old() or {}, ensure_ascii=False, indent=2))
    else:
        main()
