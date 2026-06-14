#!/usr/bin/env bash
# ============================================================================
# check-prereqs.sh — VSCode extension 就緒自檢（Linux / macOS / WSL）
#
# 本 extension 無常駐後端：掃描與 cheatsheet 都是執行指令時即時 subprocess
# 呼叫 python + claude。此腳本確認環境就緒，非啟動 server。
# ============================================================================
set -uo pipefail
EXT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # vscode-extension/
REPO_ROOT="$(dirname "$EXT_DIR")"                          # gs-tech-radar/
BRIDGE="$EXT_DIR/bridge/techbridge.py"
ok=1

echo ""
echo "==== GS Tech Radar VSCode extension — 就緒自檢 ===="

# [1] python
PY="$(command -v python3 || command -v python || true)"
if [ -n "$PY" ]; then echo "  [v] python  : $PY"
else echo "  [x] python 不在 PATH（掃描會失敗）"; ok=0; fi

# [2] claude CLI
if command -v claude >/dev/null 2>&1; then echo "  [v] claude  : $(command -v claude)"
else echo "  [!] claude CLI 不在 PATH → 可掃描但無法產生 cheatsheet"; fi

# [3] bridge 自我測試：掃 extension 自己這個資料夾
if [ -n "$PY" ]; then
  echo "  ... 跑 bridge scan 自我測試"
  out="$("$PY" "$BRIDGE" scan --root "$REPO_ROOT" "$EXT_DIR" 2>&1 || true)"
  count="$(printf '%s' "$out" | "$PY" -c "import sys,json;
try:
    d=json.load(sys.stdin); print('ERR:'+d['error'] if 'error' in d else str(len(d['techs']))+'/'+str(d['file_count']))
except Exception as e: print('BAD')" 2>/dev/null)"
  case "$count" in
    ERR:*) echo "  [x] bridge 錯誤：${count#ERR:}"; ok=0 ;;
    BAD|"") echo "  [x] bridge 輸出非預期：$(printf '%s' "$out" | head -c 200)"; ok=0 ;;
    *) echo "  [v] bridge OK：偵測到 ${count%%/*} 項技術（掃 ${count##*/} 檔）" ;;
  esac
fi

echo ""
if [ "$ok" = "1" ]; then
  echo "就緒 ✓  開始使用："
  echo "  1. VSCode 開啟資料夾 $EXT_DIR"
  echo "  2. 按 F5 開出 Extension Development Host"
  echo "  3. 在新視窗開任一專案 → 點左側雷達圖示 → 掃描技術棧"
else
  echo "尚有缺項，請依上方修正後再試。"
fi
