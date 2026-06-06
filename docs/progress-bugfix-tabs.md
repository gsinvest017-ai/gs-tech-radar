# KG / Timeline / Cheatsheet / Comparison Bug 修正

## 目標
三個 tab 的顯示問題：KG Load all 空、Timeline/Cheatsheet 無資料、Comparison 500。
根因：前端 state.analysisCache 只在當次 session 填入；後端 analysis route 無 try/except。

## 計畫 milestones
- [x] M1 — 後端：`GET /api/analyses`（從 DB 讀所有既有分析）+ analysis route try/except + analyzer JSON 提取更健壯
- [x] M2 — 前端：init 載入 analysisCache；KG load-all 改呼叫 /api/kg；Comparison 顯示後端錯誤

## Fallback 指引
rollback: `git revert HEAD~N`
關鍵檔案: `intelligence/analyzer.py`, `web/app.py`, `web/static/app.js`

## 進度日誌

## M1 — 後端
- `intelligence/analyzer.py`: `_extract_json()` — 先直接 parse，失敗則找 `{...}` substring，避免 Claude 加前置文字時 parse 失敗
- `web/app.py`: `GET /api/analyses` — 掃所有 techs，把有 `overview` 的分析回傳成 `{name: analysis}` dict
- `web/app.py`: `tech_analysis` route 包 try/except，500 時回傳可讀錯誤訊息而非裸 traceback

## M2 — 前端
- `refreshAll()` 新增呼叫 `GET /api/analyses`，結果合併進 `state.analysisCache`（不覆蓋 session 新生成的）
- KG "Load all" 改直接呼叫 `GET /api/kg`（不帶 techs 參數 = 所有已分析 techs），只在 nodes 為空時 toast
- `loadKGForTech()` 移除 analysisCache 前置檢查，直接呼叫 `/api/kg?techs={name}`
- Comparison: 未 cache 時顯示 spinner → 呼叫 API → 失敗時顯示帶說明的錯誤，不再噴 500 給使用者看
