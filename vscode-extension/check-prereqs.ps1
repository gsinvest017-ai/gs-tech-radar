# ============================================================================
# check-prereqs.ps1 — VSCode extension 就緒自檢（Windows）
#
# 注意：本 extension「沒有常駐後端 server」。掃描與 cheatsheet 都是 extension
# 在執行指令時，透過 bridge 即時 subprocess 呼叫 python + claude。所以這支腳本
# 不是「啟動後端」，而是「確認你的環境已就緒」：
#   1. python 可用            （掃描必需）
#   2. claude CLI 可用        （產 cheatsheet 必需）
#   3. bridge 能 import 掃描核心並實際跑一次 scan（自我測試）
#
#   用法： .\check-prereqs.ps1
# ============================================================================
$ErrorActionPreference = "Continue"
$ExtDir   = Split-Path -Parent $MyInvocation.MyCommand.Path     # vscode-extension/
$RepoRoot = Split-Path -Parent $ExtDir                          # gs-tech-radar/
$Bridge   = Join-Path $ExtDir "bridge\techbridge.py"
$ok = $true

Write-Host ""
Write-Host "==== GS Tech Radar VSCode extension — 就緒自檢 ====" -ForegroundColor Yellow

# [1] python
$py = Get-Command python -ErrorAction SilentlyContinue
if ($py) { Write-Host "  [v] python  : $($py.Source)" -ForegroundColor Green }
else { Write-Host "  [x] python 不在 PATH（掃描會失敗，或於設定填 gsTechRadar.pythonPath）" -ForegroundColor Red; $ok = $false }

# [2] claude CLI
$claude = Get-Command claude -ErrorAction SilentlyContinue
if (-not $claude) { $claude = Get-Command claude.cmd -ErrorAction SilentlyContinue }
if (-not $claude) { $claude = Get-Command claude.exe -ErrorAction SilentlyContinue }
if ($claude) { Write-Host "  [v] claude  : $($claude.Source)" -ForegroundColor Green }
else { Write-Host "  [!] claude CLI 不在 PATH → 可掃描但無法產生 cheatsheet" -ForegroundColor DarkYellow }

# [3] bridge 自我測試：掃 extension 自己這個資料夾
if ($py) {
  Write-Host "  ... 跑 bridge scan 自我測試"
  $json = & $py.Source $Bridge scan --root $RepoRoot $ExtDir 2>&1 | Out-String
  try {
    $parsed = $json | ConvertFrom-Json
    if ($parsed.error) {
      Write-Host "  [x] bridge 錯誤：$($parsed.error)" -ForegroundColor Red; $ok = $false
    } else {
      Write-Host "  [v] bridge OK：掃 $($parsed.file_count) 檔，偵測到 $($parsed.techs.Count) 項技術" -ForegroundColor Green
    }
  } catch {
    Write-Host "  [x] bridge 輸出非預期：$($json.Substring(0, [Math]::Min(200,$json.Length)))" -ForegroundColor Red; $ok = $false
  }
}

Write-Host ""
if ($ok) {
  Write-Host "就緒 ✓  開始使用：" -ForegroundColor Green
  Write-Host "  1. VSCode 開啟資料夾 $ExtDir"
  Write-Host "  2. 按 F5 開出 Extension Development Host"
  Write-Host "  3. 在新視窗開任一專案 → 點左側雷達圖示 → 掃描技術棧"
} else {
  Write-Host "尚有缺項，請依上方紅字修正後再試。" -ForegroundColor Red
}
