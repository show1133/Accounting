# 日常帳務管理（Python）

參考 [日常帳務管理台](https://claude.ai/artifact/XsXvwk1vTvYHd4Q8rLo5V1)，實作繁體中文命令列與互動選單。支援收支記帳、月份與類別、預算、信用卡 PDF 帳單、財務分析、Excel / CSV / PNG 匯出，以及 GitHub 帳本上下載。

目標儲存庫：<https://github.com/show1133/Accounting/>。Python 3.10 以上，建議使用 3.12。

網頁版：<https://show1133.github.io/Accounting/>（根目錄 `index.html`，由 GitHub Pages 提供）。網頁資料只存在各自瀏覽器的 localStorage，不會寫入儲存庫。

**隱私注意：此儲存庫為公開，以使用免費 GitHub Pages。** 任何上傳到儲存庫的帳本、Actions 日誌與報表都會被他人讀取；刪除檔案不會清除 Git 歷史。程式預設拒絕公開上傳，也不會把權杖寫入帳本或同步狀態。真實帳務建議只存在本機，或另用私人儲存庫同步。

## Windows 快速開始

在專案目錄使用 PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe accounting.py
```

不必啟用虛擬環境即可使用。下列指令中的 `python` 可替換為 `.\.venv\Scripts\python.exe`。

macOS / Linux：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
.venv/bin/python accounting.py
```

首次操作會建立 `config.json`（類別、預算、帳單關鍵字對照）與 `data/ledger.json`。本機記帳不需要 GitHub 權杖；空白帳本不會加入示範資料。金額以 Decimal 計算到小數二位，不接受零、負數、無限值或未來日期。

## 指令

`python accounting.py` 與 `python -m ledger.cli` 等效。

| 指令 | 用途 |
| --- | --- |
| `python accounting.py` | 中文互動式選單 |
| `python accounting.py add --category 餐飲 --item 午餐 --amount 180` | 新增今天的支出 |
| `python accounting.py add --date 2026-10-05 --category 薪資 --item 十月薪資 --amount 60000 --kind 收入 --payment 轉帳` | 指定日期與收入 |
| `python accounting.py list --month 2026-10 --category 餐飲 --keyword 午餐` | 查詢 |
| `python accounting.py delete --id 12` | 確認後刪除、自動備份 |
| `python accounting.py category add 寵物` | 新增類別，另有 `remove 名稱` / `list` |
| `python accounting.py month add 2026-11` | 新增空白月份，另有 `remove YYYY-MM` / `list` |
| `python accounting.py budget --category 餐飲 --amount 6000` | 設定每月類別預算 |
| `python accounting.py import --pdf statement.pdf --year 2026` | 預覽並匯入信用卡帳單 |
| `python accounting.py import --json web-export.json` | 匯入參考網頁匯出的 JSON |
| `python accounting.py analyze --chart` | 收支、預算、占比分析，另存 PNG |
| `python accounting.py export --excel reports/ledger.xlsx --csv reports/ledger.csv` | 匯出報表 |
| `python accounting.py sync --dry-run` | 不連線的上傳試跑 |
| `python accounting.py sync` | 上傳帳本 |
| `python accounting.py sync --pull` | 下載遠端帳本 |

非互動執行的刪除或匯入需加 `--yes`。被帳務使用的類別或月份不可移除；新增記帳時也可直接輸入新類別，不影響過去資料。

## 帳單與網頁 JSON 匯入

PDF 匯入接受 `2026/10/05 商店名稱 1,280`、`10/05 商店名稱 1280.00` 與民國日期 `115/10/05` 等文字列，也接受消費日後附入帳日。無年份時使用 `--year`，跨年帳單請分年度核對。負金額視為退款收入，摘要列不匯入。

不同銀行的 PDF 格式不一致，並非所有帳單都能直接解析；加密檔需先解密。請務必核對預覽，金額辨識有誤時不要匯入。

掃描影像型帳單（PDF 沒有文字）會自動改用 **Windows 10/11 內建的繁體中文 OCR**，完全在本機處理，不會上傳帳單。OCR 可能誤讀少數字元；日期或金額無效的行會被略過並提示數量，請對照帳單補登。非 Windows 環境需先自行 OCR。

匯入時輸入 `y` 全部匯入、`n` 取消，或序號如 `1,3,5`。以「日期、金額、項目」去重，匯入後重新配置編號。同日同金額同項目的真實重複消費可改用 `add` 手動新增。

網頁「GitHub 同步」匯出的 JSON 請存成 `web-export.json`，最外層為帳務陣列；`cat`、`type`、`pay` 會自動對應到類別、收支、支付方式。建議使用匯入指令而非直接覆蓋帳本，才能保留備份與去重。

## Excel 版面

- **總表**：每月收入、支出、結餘、儲蓄率、支出環比、合計、全期類別占比、最新月份預算，以及每月收支長條圖。
- **每月工作表**：名稱為 `YYYY-MM`，日期、類別、項目、收支、金額、支付方式、備註；包含篩選、凍結窗格與月度小計。
- 單筆支出達一萬元以紅字粗體標示，預算超支與負結餘標紅。文字以文字儲存，避免帳務內容被當成 Excel 公式執行。

儲蓄率為結餘 / 收入；無收入時顯示 0。支出環比比較前一個報表月份，沒有基期或基期支出為零時顯示未提供。下期支出參考為最近三個有紀錄月份平均，並非財務建議。

## GitHub 設定與同步

1. GitHub > Settings > Developer settings > Personal access tokens > Fine-grained tokens。
2. Repository access 只選 `show1133/Accounting`，Permissions 設定 **Contents: Read and write**。
3. 在本機 `.env` 填入 `GITHUB_TOKEN`，不要把權杖貼到程式、聊天、GitHub 檔案或指令參數。

範例設定檔已預設 `GITHUB_OWNER=show1133`、`GITHUB_REPO=Accounting`、`GITHUB_BRANCH=main`、`LEDGER_PATH=data/ledger.json`。若預設分支不是 main 請修改設定。同步僅傳送帳本，不會上傳 `.env`、設定、備份或日誌。

```powershell
python accounting.py sync --dry-run
python accounting.py sync
```

私人儲存庫可直接上傳；若確定要公開帳務，才使用 `python accounting.py sync --allow-public`。

首次接手已有帳本的儲存庫，請先在空白本機帳本執行 `python accounting.py sync --pull`。本機已有資料時，下載必須明確加 `--force`，原資料會先備份。

遠端版本改變時，程式拒絕覆寫。先匯出本機 JSON 的副本，使用 `sync --pull --force` 下載，再以 `import --json 副本.json` 合併，確認後上傳。只有確定以本機帳本取代遠端時，才使用 `sync --force`。此工具採整份帳本同步，不會自動合併多人修改或同時寫入；請避免同時開啟多個記帳程序。

GET 請求會對暫時性錯誤重試；PUT 不自動重送，避免逾時後產生不確定的重複更新。權限、版本衝突與連線失敗會顯示中文錯誤，且不回印 GitHub 原始錯誤內容。

## 在 GitHub 操作

將本專案程式（包含隱藏的 `.github` 資料夾）上傳到 <https://github.com/show1133/Accounting/> 的預設分支。不要上傳 `.env` 或備份；本機帳本已被 `.gitignore` 排除，需透過程式明確同步。

1. 儲存庫 > **Actions** > **Daily Accounting** > **Run workflow**。
2. `operation` 選 `add` 新增帳務，填入日期、類別、項目、金額與收支；選 `report` 則只產生報表。
3. 私人儲存庫不必勾 `allow_public`；公開儲存庫必須確認勾選，代表接受帳務、執行日誌與報表公開。
4. 完成後在該次執行的 **Artifacts** 下載 `accounting-reports`，內含 Excel、CSV 與 PNG，保留 7 天。

Actions 使用 GitHub 自動提供的 `GITHUB_TOKEN`，無需將本機 PAT 上傳。新增記帳會先讀取遠端帳本，再透過 Contents API 寫回同一分支，預設日期採台灣時區。若有分支保護或組織限制，請允許對應的寫入權限，或改用可寫入的分支。

GitHub Pages 只提供 `index.html` 靜態網頁，不能執行 Python；Python 程式在本機使用或透過 Actions 手動執行。啟用 Pages：Settings > Pages > Source 選 **Deploy from a branch**，Branch 選 `main`、資料夾 `/ (root)`。

## 備份與測試

帳本以原子替換寫入，每次更新前備份到 `data/backup/`，保留最近 5 份。還原前先關閉程式，再把所需備份複製回 `data/ledger.json`。損壞或驗證失敗的帳本不會自動清空。

日誌位於 `logs/ledger.log`，單檔 1 MB，輪替保留 3 份；程式錯誤訊息與日誌會遮蔽已設定的權杖。請自行定期備份，GitHub 同步不等於加密或完整備援。

```powershell
python -m pytest -q
```

47 項測試涵蓋資料驗證、原子寫入失敗、備份輪替、帳單解析與去重、分析、Excel、CSV 公式防護、CLI 流程，以及 GitHub 公開上傳、衝突、下載與權杖保護。同步測試使用模擬，不使用真實權杖或網路。每次 push / pull request 另有 GitHub Actions 執行 Windows 與 Linux 測試。

## 專案結構

```text
accounting.py                 執行入口
ledger/models.py              資料模型與驗證
ledger/storage.py             原子儲存、備份、設定與 CSV
ledger/statement.py           PDF 帳單解析與去重
ledger/analytics.py           分析與 PNG 圖表
ledger/excel_export.py        Excel 每月工作表與總表
ledger/github_sync.py         GitHub Contents API 上下載
ledger/cli.py                 命令列與中文選單
tests/test_ledger.py           自動測試
.github/workflows/             測試與手動帳務管理
```
