# Owner 自動匯入所有 repo 進度

## 目標
偵測到 owner 後自動從 GitHub 批次匯入該 owner 所有 repo（只存 metadata，不觸發 tech scan）；
使用者明確點選某個 repo 後才觸發分析流程。

## 計畫 milestones
- [x] M1 — `gh_scanner.fetch_owner_repos(owner)` — GitHub API 取得 owner 所有 repo
- [x] M2 — `POST /api/import-owner/{owner}` — 批次 upsert metadata，不觸發 scan；`POST /api/repos` 加 `auto_scan` 參數
- [x] M3 — 前端：init 時呼叫 import-owner；未 scan repo 顯示「點擊掃描」；click 觸發 scan

## Fallback 指引
rollback: `git revert HEAD~N` 或 `git reset --hard <hash>`
關鍵檔案: `scanner/gh_scanner.py`, `web/app.py`, `web/static/app.js`, `web/static/index.html`

## 進度日誌

## M1 — fetch_owner_repos
`scanner/gh_scanner.py` 新增 `fetch_owner_repos(owner, max_pages=10)`，
呼叫 `GET /users/{owner}/repos?per_page=100&sort=pushed`，
分頁直到最後一頁，回傳統一格式 list。
測試：gsinvest017-ai 取回 18 repos。

## M2 — import-owner API + auto_scan
`web/app.py` 新增 `POST /api/import-owner/{owner}`：
批次呼叫 `fetch_owner_repos`，逐一 upsert DB，回傳 `{imported, skipped, total}`。
`POST /api/repos` 新增 `auto_scan: bool = True` 欄位；
前端手動加 repo 時送 `auto_scan: false`。

## M3 — 前端 click-to-scan
- init：呼叫 `/api/me` 後立即 `POST /api/import-owner/{login}`，若 imported > 0 顯示 toast
- sidebar：未掃 repo 顯示 `▷` 按鈕（`.scan-cta`）、較暗樣式（`.not-scanned`）
- overview card：未掃顯示「▷ Scan this repo」金色按鈕 + stars/forks/language；已掃才顯示 tech tags 和完整 metrics
- `triggerScan(id)` 統一入口：呼叫 `POST /api/repos/{id}/scan` 並開始 poll
