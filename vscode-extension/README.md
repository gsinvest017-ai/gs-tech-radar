# GS Tech Radar — VSCode Extension

在 VSCode 側欄掃描**目前 workspace** 的技術棧，點任一技術用 **Claude Code**
產生 AI cheatsheet，並可匯出成 Markdown。

完全重用 [gs-tech-radar](../) 的偵測規則（`scanner/tech_detector.py`）與分析器
（`intelligence/analyzer.py`），不在 TS 端重寫，規則只有一份、不會分歧。

## 快速開始

> **本 extension 沒有常駐後端 server**——掃描與 cheatsheet 都是執行指令時
> 即時 subprocess 呼叫 `python` + `claude`。所以不用「啟動後端」，只要確認環境就緒。

**① 就緒自檢**（確認 python / claude / bridge 都 OK）：
```powershell
cd C:\Users\User\gs-tech-radar\vscode-extension
.\check-prereqs.ps1              # Windows
```
```bash
bash check-prereqs.sh            # Linux / macOS / WSL
```

**② 啟動**：VSCode 開啟本資料夾 → 按 **F5** → 在跳出的 Extension Development Host 視窗
開任一專案。

**③ 用**：點左側活動列 **雷達圖示** →「掃描技術棧」→ 點任一技術產生 AI cheatsheet
→ 面板右上「⬇ 匯出 Markdown」。

## 功能

- **掃描技術棧**：讀 workspace 的 `requirements*.txt` / `pyproject.toml` /
  `package.json` / `go.mod` / `Cargo.toml` + 檔案清單，偵測語言、框架、資料庫、
  基礎設施（Docker / GitHub Actions / Terraform…），在 **Tech Radar** 側欄依
  分類樹狀列出。
- **AI Cheatsheet**：點任一技術 → 用 `claude --print` 產生 overview、現況、
  最佳實務、安裝/快速上手/常見模式的 cheatsheet、替代方案比較、時間軸，
  以 webview 呈現。
- **匯出 Markdown**：把 cheatsheet 存成 `<技術>-cheatsheet.md`。

## 架構

```
VSCode (extension.js, 純 JS 零建置)
   │  child_process
   ▼
bridge/techbridge.py  ──import──►  gs-tech-radar/scanner.tech_detector   (掃描)
                      ──import──►  gs-tech-radar/intelligence.analyzer    (cheatsheet → claude CLI)
```

- **掃描**純 stdlib，離線可用。
- **cheatsheet** 走 `claude` CLI（**免 API key**，用你既有的 Claude Code 登入）。
- analyzer 頂層會 `from storage import db`（aiosqlite）；bridge 已注入 stub
  storage 模組避開該依賴，因此 **不需安裝 gs-tech-radar 的任何套件**。

## 前置需求

- VSCode 1.75+
- `python`（3.11+）在 PATH，或在設定指定 `gsTechRadar.pythonPath`
- 產生 cheatsheet 需要 `claude` CLI 在 PATH（Claude Code 已安裝並登入）

## 安裝（開發模式）

1. VSCode 開啟 `gs-tech-radar/vscode-extension/` 這個資料夾。
2. 按 **F5**（Run Extension）→ 開出一個 Extension Development Host 視窗。
3. 在新視窗開任一專案資料夾，點左側活動列的 **雷達圖示** → 「掃描技術棧」。

> 或打包成 `.vsix`：`npx @vscode/vsce package`（需 Node），再
> `code --install-extension gs-tech-radar-0.1.0.vsix`。

## 設定

| 設定鍵 | 預設 | 說明 |
|--------|------|------|
| `gsTechRadar.pythonPath` | `python` | 跑 bridge 的 Python 直譯器 |
| `gsTechRadar.techRadarRoot` | （空） | gs-tech-radar repo 根；空＝自動取 extension 上層 |
| `gsTechRadar.analyzeTimeoutSec` | `120` | claude CLI 逾時秒數 |

## 檔案

```
vscode-extension/
├── package.json          extension manifest（view container / commands / config）
├── extension.js          主邏輯：tree provider + webview + 匯出（純 CommonJS）
├── bridge/techbridge.py  Python bridge：scan / analyze 兩個子指令
├── assets/radar.svg      活動列圖示
└── README.md
```

## 疑難排解

- **掃描失敗 "cannot import scanner.tech_detector"**：`techRadarRoot` 指錯，
  或 extension 被搬離 gs-tech-radar；到設定填上 repo 根的絕對路徑。
- **cheatsheet 失敗 "claude CLI not found"**：裝 Claude Code 並確認 `claude`
  在 PATH（Windows 是 `claude.cmd`）。
- **Python 找不到**：設 `gsTechRadar.pythonPath` 為絕對路徑（如 venv 內的 python）。
- **大 repo 掃很久**：bridge 會跳過 node_modules/.venv/dist 等重目錄，上限 4 萬檔。
