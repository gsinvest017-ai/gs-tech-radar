"""VSCode extension bridge — reuse gs-tech-radar 的掃描與分析核心，免重寫規則。

兩個子指令（皆輸出單一 JSON 到 stdout）：

    python techbridge.py scan    --root <repo> <workspace_dir>
    python techbridge.py analyze --root <repo> "<tech_name>" "<category>"

scan：掃 workspace 的 manifest 檔 + 檔案清單 → 重用 scanner.tech_detector
      的 detect_from_* + merge_matches，輸出技術棧。純 stdlib。

analyze：重用 intelligence.analyzer.generate_analysis（走 `claude --print`，
      免 API key）。analyzer 模組頂層 `from storage import db` 會拉進 aiosqlite；
      generate_analysis 本身並不用 db，故先塞一個 stub storage 模組進 sys.modules
      避開該第三方依賴。

--root 指向 gs-tech-radar repo 根（含 scanner/ intelligence/）；省略時用
TECH_RADAR_ROOT 環境變數，再不行用本檔往上三層推算。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import types
from pathlib import Path

# 掃描時跳過的重目錄（保留 .github 以便偵測 GitHub Actions）
_SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "env", "__pycache__",
    "dist", "build", ".next", "target", ".mypy_cache", ".pytest_cache",
    ".idea", ".gradle", ".cache", "site-packages", ".tox", "coverage",
    "out", "bin", "obj", ".turbo", ".parcel-cache",
}
_MAX_FILES = 40000


def _resolve_root(root_arg: str | None) -> Path:
    if root_arg:
        return Path(root_arg).resolve()
    env = os.environ.get("TECH_RADAR_ROOT")
    if env:
        return Path(env).resolve()
    # bridge 位於 <root>/vscode-extension/bridge/techbridge.py
    return Path(__file__).resolve().parents[2]


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False))
    sys.stdout.flush()


def _fail(msg: str, code: int = 1) -> None:
    _emit({"error": msg})
    sys.exit(code)


# ── scan ────────────────────────────────────────────────────────────────
def cmd_scan(root: Path, workspace: str) -> None:
    ws = Path(workspace).resolve()
    if not ws.is_dir():
        _fail(f"workspace not a directory: {ws}")

    sys.path.insert(0, str(root))
    try:
        from scanner import tech_detector as td
    except Exception as exc:  # noqa: BLE001
        _fail(f"cannot import scanner.tech_detector from {root}: "
              f"{type(exc).__name__}: {exc}")

    rel_paths: list[str] = []        # posix 相對路徑（給 detect_from_file_list）
    manifests: dict[str, list[Path]] = {}  # 分類後的 manifest 絕對路徑
    truncated = False

    for cur, dirs, files in os.walk(ws):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".egg-info")]
        for fn in files:
            abs_p = Path(cur) / fn
            rel = abs_p.relative_to(ws).as_posix()
            rel_paths.append(rel)
            if len(rel_paths) >= _MAX_FILES:
                truncated = True
                break
            low = fn.lower()
            if low.startswith("requirements") and low.endswith(".txt"):
                manifests.setdefault("req", []).append(abs_p)
            elif low == "pyproject.toml":
                manifests.setdefault("pyproject", []).append(abs_p)
            elif low == "package.json":
                manifests.setdefault("package", []).append(abs_p)
            elif low == "go.mod":
                manifests.setdefault("go", []).append(abs_p)
            elif low == "cargo.toml":
                manifests.setdefault("cargo", []).append(abs_p)
        if truncated:
            break

    def _read(p: Path) -> str:
        try:
            return p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    groups: list[list] = []
    for p in manifests.get("req", []):
        groups.append(td.detect_from_requirements(_read(p), p.name))
    for p in manifests.get("pyproject", []):
        groups.append(td.detect_from_pyproject(_read(p)))
    for p in manifests.get("package", []):
        groups.append(td.detect_from_package_json(_read(p)))
    for p in manifests.get("go", []):
        groups.append(td.detect_from_go_mod(_read(p)))
    for p in manifests.get("cargo", []):
        groups.append(td.detect_from_cargo_toml(_read(p)))
    groups.append(td.detect_from_file_list(rel_paths))

    merged = td.merge_matches(groups)
    _emit({
        "scanned_dir": str(ws),
        "file_count": len(rel_paths),
        "truncated": truncated,
        "techs": [
            {
                "name": m.name,
                "category": m.category,
                "confidence": round(m.confidence, 3),
                "version": m.version,
                "source_file": m.source_file,
            }
            for m in merged
        ],
    })


# ── analyze ─────────────────────────────────────────────────────────────
def _install_storage_stub() -> None:
    """analyzer 頂層 `from storage import db` 需要 aiosqlite；generate_analysis
    不碰 db，故塞一個 stub 模組避開第三方依賴。"""
    if "storage" in sys.modules:
        return
    storage = types.ModuleType("storage")
    db_stub = types.ModuleType("storage.db")
    storage.db = db_stub  # type: ignore[attr-defined]
    sys.modules["storage"] = storage
    sys.modules["storage.db"] = db_stub


def cmd_analyze(root: Path, tech_name: str, category: str, timeout: int) -> None:
    sys.path.insert(0, str(root))
    _install_storage_stub()
    try:
        from intelligence import analyzer
    except Exception as exc:  # noqa: BLE001
        _fail(f"cannot import intelligence.analyzer from {root}: "
              f"{type(exc).__name__}: {exc}")

    # 直接走同步內部呼叫，避開 asyncio / executor，並套用自訂 timeout。
    prompt = analyzer._PROMPT_TEMPLATE.format(tech=tech_name, category=category)
    try:
        raw = analyzer._run_claude_sync(prompt.encode("utf-8"), timeout)
        analysis = analyzer._extract_json(raw)
    except Exception as exc:  # noqa: BLE001
        _fail(f"analyze failed: {type(exc).__name__}: {exc}")
    _emit({"tech": tech_name, "category": category, "analysis": analysis})


def main() -> None:
    # --root 可放在 subcommand 前或後（parent parser 讓兩處都吃得到）
    root_parent = argparse.ArgumentParser(add_help=False)
    root_parent.add_argument("--root", default=None, help="gs-tech-radar repo root")

    ap = argparse.ArgumentParser(prog="techbridge", parents=[root_parent])
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", parents=[root_parent])
    s.add_argument("workspace")

    a = sub.add_parser("analyze", parents=[root_parent])
    a.add_argument("tech_name")
    a.add_argument("category")
    a.add_argument("--timeout", type=int, default=120)

    args = ap.parse_args()
    root = _resolve_root(args.root)
    if not root.is_dir():
        _fail(f"tech-radar root not found: {root}")

    if args.cmd == "scan":
        cmd_scan(root, args.workspace)
    elif args.cmd == "analyze":
        cmd_analyze(root, args.tech_name, args.category, args.timeout)


if __name__ == "__main__":
    main()
