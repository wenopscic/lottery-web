# 彩票即時開獎資訊 — GitHub 自動更新完整設定指南

本指南帶你把網站放上 GitHub，並用 **GitHub Actions + GitHub Pages** 做到「定時自動抓取開獎號碼 → 自動更新網站」。

---

## 一、你會用到的檔案

| 檔案 | 用途 | 放哪裡 |
|---|---|---|
| `index.html` | 網站主頁 | repo 根目錄 |
| `data/snapshot.json` | 開獎資料快照（網站讀取它） | `data/` 資料夾 |
| `update.py` | 抓取程式（寫入 snapshot.json） | repo 根目錄 |
| `.github/workflows/update-lottery.yml` | 定時排程設定 | `.github/workflows/` 資料夾 |

> ⚠️ 注意：`update.py` 與 workflow 檔**不要**放進網站發布目錄（例如 Teamily 的網頁資料夾），
> 它們是後端程式，只放在 GitHub repo 裡。

---

## 二、逐步設定

### 步驟 1：建立 GitHub repo
1. 登入 GitHub → 右上角 **+** → **New repository**。
2. Repository name 例如 `lottery-live`，選 **Public**（GitHub Pages 免費版需公開）。
3. 勾選 **Add a README file** → **Create repository**。

### 步驟 2：上傳檔案
在 repo 頁面點 **Add file → Upload files**，上傳：
- `index.html`
- `update.py`

再建立資料夾與 workflow：
1. **Add file → Create new file**，檔名輸入 `data/snapshot.json`（輸入斜線會自動建資料夾），貼上快照內容。
2. 再 **Create new file**，檔名輸入 `.github/workflows/update-lottery.yml`，貼上 workflow 內容。

> 小技巧：也可以在本機用 git 指令一次推上去：
> ```bash
> git clone https://github.com/<你的帳號>/lottery-live.git
> cd lottery-live
> # 把 index.html、update.py、data/snapshot.json、.github/workflows/update-lottery.yml 放進來
> git add .
> git commit -m "init"
> git push
> ```

### 步驟 3：開啟 GitHub Pages
1. repo → **Settings** → 左側 **Pages**。
2. **Source** 選 **Deploy from a branch**。
3. **Branch** 選 `main`、資料夾選 `/ (root)` → **Save**。
4. 等 1～2 分鐘，頁面上方會出現網址：`https://<你的帳號>.github.io/lottery-live/`

### 步驟 4：確認 Actions 正常執行
1. repo → 上方 **Actions** 分頁。
2. 左側會看到 **Update Lottery Snapshot**。
3. 點進去 → 右側 **Run workflow** 按鈕可**手動觸發測試**。
4. 點任一次執行紀錄，可展開每個 step 看**執行日誌**（`Run update.py` 會印出 `[OK]` / `[SAME]` / `[FAIL]` 等訊息）。
5. 執行成功後，`data/snapshot.json` 會被自動 commit，網站隨之更新。

---

## 三、排程時間怎麼設（台北 ↔ UTC 換算）

**GitHub Actions 的 cron 一律用 UTC，且不能設時區。台北時間 = UTC + 8。**

| 台北時間 | UTC | cron 寫法 |
|---|---|---|
| 每天 21:00 | 13:00 | `0 13 * * *` |
| 每天 21:00、22:00、23:00 | 13:00、14:00、15:00 | `0 13,14,15 * * *` ← **本專案預設** |
| 每天 20:00–23:59 每 12 分鐘 | 12:00–15:59 | `*/12 12-15 * * *` |
| 每天 07:00–23:00 每小時（BINGO） | 23:00 及 00:00–15:00 | `0 23 * * *` ＋ `0 0-15 * * *` |

> ⚠️ GitHub 免費排程在尖峰時段可能**延遲數分鐘到數十分鐘**，這是平台已知行為。
> 若需要「準點」執行，建議改用自架主機的 cron 或 Cloudflare Cron Triggers。

---

## 四、常見錯誤排除

| 症狀 | 原因 | 解法 |
|---|---|---|
| `Permission denied` / push 被拒 | workflow 缺寫入權限 | 確認 workflow 有 `permissions: contents: write`；並到 Settings → Actions → General → Workflow permissions 選 **Read and write permissions** |
| 排程時間對不上 | 誤把台北時間當 UTC | 記得 **台北 = UTC + 8**，cron 要寫 UTC |
| `playwright install` 失敗 | 缺系統函式庫 | 用 `playwright install --with-deps chromium`（workflow 已含） |
| `ModuleNotFoundError: playwright` | 沒裝套件 | workflow 的 `pip install playwright` 步驟要保留 |
| 香港六合彩抓不到 | 官網改版或渲染逾時 | 檢查 `fetch_hkjc()` 的解析規則；必要時調高 `wait_for_timeout` |
| 中國彩種抓不到 | 500.com XML 暫時異常 | 程式會**保留舊資料並標記延遲**，不會清空；稍後重試即可 |
| Actions 完全沒跑 | repo 60 天無活動會暫停排程 | 進 Actions 分頁按 **Enable workflow**，或手動觸發一次 |

---

## 五、本機測試（可選）

```bash
pip install playwright
playwright install chromium

python3 update.py --force --print   # 立即抓取並印出結果（不寫檔）
python3 update.py --force           # 立即抓取並寫入 data/snapshot.json
python3 update.py --status          # 只看目前快照狀態
```

---

## 六、資料來源與合法性

| 彩種 | 來源 | 取得方式 |
|---|---|---|
| 中國福彩 3D | 500.com 公開 XML | HTTP 抓取 |
| 中國體彩 排列3 / 排列5 | 500.com 公開 XML | HTTP 抓取 |
| 香港六合彩 | 香港賽馬會 HKJC 官網 | 無頭瀏覽器渲染 |
| 台灣 BINGO BINGO | 台灣彩券官方 API | HTTP 抓取 |

> 中國福彩/體彩「官方」端點（cwl.gov.cn / sporttery.cn）具反爬蟲保護（HTTP 403/567），
> 故改用 500.com 公開 XML（官方開獎結果之公開轉載）。
> 香港六合彩官方 GraphQL 端點具白名單限制，故以無頭瀏覽器渲染官網取得。

**澳門六合彩**：經查證澳門特區政府、DICJ 與司警局均明確表示「從未批准任何公司經營澳門六合彩」，
所有以「澳門六合彩」名義之網站均屬虛假及非法。基於來源非法，本程式**不抓取**任何相關號碼，
公開網站亦已移除該彩種（相關研究僅保留於內部監測頁）。

---

⚠️ 本站僅彙整公開資訊，實際開獎結果以官方公告為準；未滿 18 歲不得購買或兌領彩券，請理性投注。
