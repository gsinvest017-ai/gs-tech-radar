# KG / Timeline / Cheatsheet / Comparison Bug 修正

## 目標
三個 tab 的顯示問題：KG Load all 空、Timeline/Cheatsheet 無資料、Comparison 500。
根因：前端 state.analysisCache 只在當次 session 填入；後端 analysis route 無 try/except。

## 計畫 milestones
- [ ] M1 — 後端：`GET /api/analyses`（從 DB 讀所有既有分析）+ analysis route try/except + analyzer JSON 提取更健壯
- [ ] M2 — 前端：init 載入 analysisCache；KG load-all 改呼叫 /api/kg；Comparison 顯示後端錯誤

## Fallback 指引
rollback: `git revert HEAD~N`
關鍵檔案: `intelligence/analyzer.py`, `web/app.py`, `web/static/app.js`

## 進度日誌
