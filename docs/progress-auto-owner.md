# Auto-owner 修正進度

## 目標
輸入欄若不含 `/`，自動 prepend 目前 gh 登入 user 為 owner，
讓使用者只需輸入 repo name（或 owner/repo 兩者皆可）。

## 計畫 milestones
- [x] M1 — `gh_scanner.get_current_gh_user()` — 從 `gh api user` 取得登入帳號
- [x] M2 — `web/app.py` `add_repo` — 若無 `/` 則 prepend owner；新增 `GET /api/me`
- [x] M3 — 前端 placeholder 動態顯示登入帳號；sidebar badge `@login`

## 進度日誌

## M1 — get_current_gh_user()
`scanner/gh_scanner.py` 新增 `get_current_gh_user()`，呼叫 `gh api user --jq .login`，
結果 module-level cache，避免重複呼叫。回傳 `gsinvest017-ai`。

## M2 — auto-prepend owner
`web/app.py` `add_repo`：若 `url` 不含 `/`（排除 https:// 前綴），
自動 prepend `get_current_gh_user()`。同步新增 `GET /api/me` 供前端查詢。

## M3 — 前端 UX
`index.html`：`placeholder` 改為「repo-name 或 owner/repo」，
sidebar label 右側加 `#gh-user-badge` span。
`app.js`：init 時呼叫 `/api/me`，動態把 placeholder 改為「repo-name 或 {login}/repo」，
badge 顯示 `@gsinvest017-ai`。

## Fallback 指引
若需 rollback：`git revert HEAD~N` 或 `git reset --hard <hash>`
相關檔案：`scanner/gh_scanner.py`、`web/app.py`、`web/static/index.html`
