# Owner 自動匯入所有 repo 進度

## 目標
偵測到 owner 後自動從 GitHub 批次匯入該 owner 所有 repo（只存 metadata，不觸發 tech scan）；
使用者明確點選某個 repo 後才觸發分析流程。

## 計畫 milestones
- [ ] M1 — `gh_scanner.fetch_owner_repos(owner)` — GitHub API 取得 owner 所有 repo
- [ ] M2 — `POST /api/import-owner/{owner}` — 批次 upsert metadata，不觸發 scan；`POST /api/repos` 加 `auto_scan` 參數
- [ ] M3 — 前端：init 時呼叫 import-owner；未 scan repo 顯示「點擊掃描」；click 觸發 scan

## Fallback 指引
rollback: `git revert HEAD~N` 或 `git reset --hard <hash>`
關鍵檔案: `scanner/gh_scanner.py`, `web/app.py`, `web/static/app.js`, `web/static/index.html`

## 進度日誌
