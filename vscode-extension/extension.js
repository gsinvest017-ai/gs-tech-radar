/* GS Tech Radar — VSCode extension（零建置純 JS）
 * ---------------------------------------------------------------------------
 * 掃描目前 workspace 的技術棧（重用 gs-tech-radar 的 scanner.tech_detector），
 * 在側欄樹狀列出；點任一技術用 Claude Code CLI 產生 AI cheatsheet（重用
 * intelligence.analyzer），以 webview 呈現並可匯出成 Markdown。
 *
 * 與 Python 核心的橋接：bridge/techbridge.py（subprocess，輸出 JSON）。
 */
"use strict";

const vscode = require("vscode");
const cp = require("child_process");
const path = require("path");
const fs = require("fs");

let provider = null;
let lastAnalysis = null; // { tech, analysis }

function activate(context) {
  provider = new TechProvider();
  context.subscriptions.push(
    vscode.window.createTreeView("gsTechRadar.techList", { treeDataProvider: provider }),
    vscode.commands.registerCommand("gsTechRadar.scan", () => scan(context)),
    vscode.commands.registerCommand("gsTechRadar.refresh", () => scan(context)),
    vscode.commands.registerCommand("gsTechRadar.showCheatsheet", (item) => showCheatsheet(context, item)),
    vscode.commands.registerCommand("gsTechRadar.exportCheatsheet", () => exportCheatsheet())
  );
}

function deactivate() {}

/* ── 設定 / 路徑 ─────────────────────────────────────────────────────── */
function cfg() { return vscode.workspace.getConfiguration("gsTechRadar"); }

function techRadarRoot(context) {
  const c = (cfg().get("techRadarRoot") || "").trim();
  // extension 位於 <root>/vscode-extension，預設取上一層
  return c || path.resolve(context.extensionPath, "..");
}
function bridgePath(context) {
  return path.join(context.extensionPath, "bridge", "techbridge.py");
}

function runBridge(context, args, timeoutMs) {
  return new Promise((resolve, reject) => {
    const py = cfg().get("pythonPath") || "python";
    const full = [bridgePath(context), "--root", techRadarRoot(context), ...args];
    cp.execFile(py, full,
      { maxBuffer: 32 * 1024 * 1024, timeout: timeoutMs || 0, windowsHide: true },
      (err, stdout, stderr) => {
        const out = (stdout || "").trim();
        if (!out) {
          return reject(new Error((stderr || (err && err.message) || "bridge 無輸出").slice(0, 400)));
        }
        let data;
        try { data = JSON.parse(out); }
        catch (_) { return reject(new Error("bridge 非 JSON 輸出：" + out.slice(0, 300))); }
        if (data.error) return reject(new Error(data.error));
        resolve(data);
      });
  });
}

/* ── 掃描 ────────────────────────────────────────────────────────────── */
async function pickWorkspaceFolder() {
  const folders = vscode.workspace.workspaceFolders;
  if (!folders || !folders.length) return null;
  if (folders.length === 1) return folders[0].uri.fsPath;
  const picked = await vscode.window.showWorkspaceFolderPick();
  return picked ? picked.uri.fsPath : null;
}

async function scan(context) {
  const folder = await pickWorkspaceFolder();
  if (!folder) { vscode.window.showWarningMessage("沒有開啟的 workspace 資料夾。"); return; }
  await vscode.window.withProgress(
    { location: { viewId: "gsTechRadar.techList" }, title: "掃描技術棧…" },
    async () => {
      try {
        const data = await runBridge(context, ["scan", folder]);
        provider.setTechs(data.techs || []);
        const note = data.truncated ? `（檔案過多，掃前 ${data.file_count} 個）` : `（掃 ${data.file_count} 檔）`;
        vscode.window.setStatusBarMessage(`Tech Radar：偵測到 ${(data.techs || []).length} 項技術 ${note}`, 6000);
      } catch (e) {
        vscode.window.showErrorMessage("掃描失敗：" + e.message);
      }
    });
}

/* ── Cheatsheet ──────────────────────────────────────────────────────── */
async function showCheatsheet(context, item) {
  const tech = item && item._tech;
  if (!tech) { vscode.window.showWarningMessage("請從「技術棧」清單點選一項技術。"); return; }
  const timeout = Number(cfg().get("analyzeTimeoutSec")) || 120;
  let data = null;
  await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: `用 Claude 產生「${tech.name}」cheatsheet…`, cancellable: false },
    async () => {
      try {
        data = await runBridge(context,
          ["analyze", tech.name, tech.category, "--timeout", String(timeout)],
          (timeout + 20) * 1000);
      } catch (e) {
        vscode.window.showErrorMessage("產生失敗：" + e.message +
          "（請確認已安裝 Claude Code 且 `claude` 在 PATH）");
      }
    });
  if (!data) return;
  lastAnalysis = { tech, analysis: data.analysis };
  openPanel(context, tech, data.analysis);
}

function openPanel(context, tech, a) {
  const panel = vscode.window.createWebviewPanel(
    "gsTechRadarCheatsheet", `${tech.name} — Cheatsheet`,
    vscode.ViewColumn.Active, { enableScripts: true, retainContextWhenHidden: true });
  panel.webview.html = renderHtml(panel.webview, tech, a);
  panel.webview.onDidReceiveMessage((msg) => {
    if (msg && msg.cmd === "export") exportCheatsheet();
  });
}

/* ── 匯出 Markdown ───────────────────────────────────────────────────── */
async function exportCheatsheet() {
  if (!lastAnalysis) { vscode.window.showWarningMessage("尚未產生任何 cheatsheet。"); return; }
  const { tech, analysis } = lastAnalysis;
  const md = buildMarkdown(tech, analysis);
  const wsFolders = vscode.workspace.workspaceFolders;
  const base = wsFolders && wsFolders.length ? wsFolders[0].uri.fsPath : process.cwd();
  const safe = tech.name.replace(/[\\/:*?"<>|]/g, "_");
  const target = await vscode.window.showSaveDialog({
    defaultUri: vscode.Uri.file(path.join(base, `${safe}-cheatsheet.md`)),
    filters: { Markdown: ["md"] },
  });
  if (!target) return;
  try {
    fs.writeFileSync(target.fsPath, md, "utf-8");
    const doc = await vscode.workspace.openTextDocument(target);
    vscode.window.showTextDocument(doc);
  } catch (e) {
    vscode.window.showErrorMessage("寫入失敗：" + e.message);
  }
}

function buildMarkdown(tech, a) {
  a = a || {};
  const L = [];
  L.push(`# ${tech.name} — Cheatsheet`, "");
  L.push(`> 分類：${tech.category}　|　生態：${a.ecosystem_status || "—"}　|　版本：${a.current_version || "—"}`, "");
  if (a.overview) L.push(a.overview, "");
  if (a.creator || a.organization || a.year_created) {
    L.push(`**作者**：${a.creator || "—"}　**組織**：${a.organization || "—"}　**誕生**：${a.year_created || "—"}`, "");
  }
  const soa = a.state_of_art || {};
  if (soa.headline) L.push(`## 現況`, "", soa.headline, "");
  if (Array.isArray(soa.latest_features) && soa.latest_features.length) {
    L.push(`### 最新特性`, "", ...soa.latest_features.map((x) => `- ${x}`), "");
  }
  if (Array.isArray(soa.best_practices) && soa.best_practices.length) {
    L.push(`### 最佳實務`, "", ...soa.best_practices.map((x) => `- ${x}`), "");
  }
  if (a.cheatsheet) L.push(`## Cheatsheet`, "", a.cheatsheet, "");
  if (Array.isArray(a.comparison) && a.comparison.length) {
    L.push(`## 替代方案比較`, "");
    for (const c of a.comparison) {
      L.push(`### vs ${c.name}`, "");
      if (Array.isArray(c.pros_over_subject)) L.push(`- 它的優勢：${c.pros_over_subject.join("；")}`);
      if (Array.isArray(c.cons_over_subject)) L.push(`- 它的劣勢：${c.cons_over_subject.join("；")}`);
      if (c.best_for) L.push(`- 適用：${c.best_for}`);
      L.push("");
    }
  }
  const tl = (a.timeline && a.timeline.events) || [];
  if (tl.length) {
    L.push(`## 時間軸`, "");
    for (const e of tl) L.push(`- **${e.year}** ${e.title}${e.description ? " — " + e.description : ""}`);
    L.push("");
  }
  return L.join("\n");
}

/* ── Tree provider ───────────────────────────────────────────────────── */
class TechProvider {
  constructor() {
    this._emitter = new vscode.EventEmitter();
    this.onDidChangeTreeData = this._emitter.event;
    this.byCat = new Map();
  }
  setTechs(techs) {
    this.byCat = new Map();
    for (const t of techs) {
      if (!this.byCat.has(t.category)) this.byCat.set(t.category, []);
      this.byCat.get(t.category).push(t);
    }
    this._emitter.fire();
  }
  getTreeItem(el) { return el; }
  getChildren(el) {
    if (!el) {
      return [...this.byCat.keys()].sort().map((cat) => {
        const it = new vscode.TreeItem(cat, vscode.TreeItemCollapsibleState.Expanded);
        it.contextValue = "category";
        it.iconPath = new vscode.ThemeIcon("folder");
        it.description = String(this.byCat.get(cat).length);
        it._cat = cat;
        return it;
      });
    }
    if (el.contextValue === "category") {
      return this.byCat.get(el._cat).map((t) => {
        const it = new vscode.TreeItem(t.name, vscode.TreeItemCollapsibleState.None);
        it.contextValue = "tech";
        it.description = [t.version, t.source_file].filter(Boolean).join("  ·  ");
        it.tooltip = `${t.name}\n分類：${t.category}\n信心：${t.confidence}\n來源：${t.source_file}`;
        it.iconPath = new vscode.ThemeIcon("package");
        it._tech = t;
        it.command = { command: "gsTechRadar.showCheatsheet", title: "產生 AI Cheatsheet", arguments: [it] };
        return it;
      });
    }
    return [];
  }
}

/* ── Webview 渲染 ────────────────────────────────────────────────────── */
function renderHtml(webview, tech, a) {
  a = a || {};
  const soa = a.state_of_art || {};
  const esc = htmlEscape;
  const list = (arr) => (Array.isArray(arr) && arr.length)
    ? `<ul>${arr.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : "";

  const meta = [
    badge("分類", tech.category), badge("生態", a.ecosystem_status),
    badge("版本", a.current_version), badge("誕生", a.year_created),
    badge("作者", a.creator), badge("組織", a.organization),
  ].filter(Boolean).join("");

  const comparison = (Array.isArray(a.comparison) ? a.comparison : []).map((c) => `
    <div class="cmp">
      <div class="cmp__name">vs ${esc(c.name)}</div>
      ${list(c.pros_over_subject) ? `<div class="cmp__pro"><b>優勢</b>${list(c.pros_over_subject)}</div>` : ""}
      ${list(c.cons_over_subject) ? `<div class="cmp__con"><b>劣勢</b>${list(c.cons_over_subject)}</div>` : ""}
      ${c.best_for ? `<div class="cmp__use"><b>適用</b> ${esc(c.best_for)}</div>` : ""}
    </div>`).join("");

  const timeline = ((a.timeline && a.timeline.events) || []).map((e) =>
    `<div class="tl"><span class="tl__y">${esc(e.year)}</span><span class="tl__t">${esc(e.title)}</span>${e.description ? `<div class="tl__d">${esc(e.description)}</div>` : ""}</div>`).join("");

  const csp = `default-src 'none'; style-src ${webview.cspSource} 'unsafe-inline'; script-src 'unsafe-inline';`;

  return `<!DOCTYPE html><html lang="zh-TW"><head>
<meta charset="UTF-8"/>
<meta http-equiv="Content-Security-Policy" content="${csp}"/>
<style>${CSS}</style></head><body>
<header class="hd">
  <div><span class="hd__name">${esc(tech.name)}</span> <span class="hd__cat">${esc(tech.category)}</span></div>
  <button id="exp">⬇ 匯出 Markdown</button>
</header>
<div class="meta">${meta}</div>
${a.overview ? `<p class="ovw">${esc(a.overview)}</p>` : ""}
${soa.headline ? `<section><h2>現況</h2><p>${esc(soa.headline)}</p></section>` : ""}
${list(soa.latest_features) ? `<section><h2>最新特性</h2>${list(soa.latest_features)}</section>` : ""}
${list(soa.best_practices) ? `<section><h2>最佳實務</h2>${list(soa.best_practices)}</section>` : ""}
${list(soa.notable_users) ? `<section><h2>知名使用者</h2>${list(soa.notable_users)}</section>` : ""}
${a.cheatsheet ? `<section><h2>Cheatsheet</h2><div class="md">${mdToHtml(a.cheatsheet)}</div></section>` : ""}
${comparison ? `<section><h2>替代方案比較</h2>${comparison}</section>` : ""}
${timeline ? `<section><h2>時間軸</h2>${timeline}</section>` : ""}
<script>
  const vscode = acquireVsCodeApi();
  document.getElementById("exp").addEventListener("click", () => vscode.postMessage({cmd:"export"}));
</script>
</body></html>`;
}

function badge(label, val) {
  if (val === undefined || val === null || val === "") return "";
  return `<span class="bdg"><i>${htmlEscape(label)}</i>${htmlEscape(val)}</span>`;
}

/* 極簡 Markdown → HTML：標題 / fenced code / 清單 / 行內 code・粗體 / 連結 / 段落 */
function mdToHtml(md) {
  const lines = String(md).replace(/\r\n/g, "\n").split("\n");
  let html = "", inCode = false, codeBuf = [], inList = false;
  const flushList = () => { if (inList) { html += "</ul>"; inList = false; } };
  for (const raw of lines) {
    const line = raw;
    const fence = line.trim().match(/^```(.*)$/);
    if (fence) {
      if (inCode) { html += `<pre><code>${htmlEscape(codeBuf.join("\n"))}</code></pre>`; codeBuf = []; inCode = false; }
      else { flushList(); inCode = true; }
      continue;
    }
    if (inCode) { codeBuf.push(line); continue; }
    const h = line.match(/^(#{1,6})\s+(.*)$/);
    if (h) { flushList(); const lvl = h[1].length; html += `<h${lvl}>${inline(h[2])}</h${lvl}>`; continue; }
    const li = line.match(/^\s*[-*+]\s+(.*)$/);
    if (li) { if (!inList) { html += "<ul>"; inList = true; } html += `<li>${inline(li[1])}</li>`; continue; }
    if (line.trim() === "") { flushList(); continue; }
    flushList();
    html += `<p>${inline(line)}</p>`;
  }
  if (inCode) html += `<pre><code>${htmlEscape(codeBuf.join("\n"))}</code></pre>`;
  flushList();
  return html;
}

function inline(s) {
  // 先轉義，再還原行內 code / 粗體 / 連結
  let t = htmlEscape(s);
  t = t.replace(/`([^`]+)`/g, (_, c) => `<code>${c}</code>`);
  t = t.replace(/\*\*([^*]+)\*\*/g, (_, c) => `<strong>${c}</strong>`);
  t = t.replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, (_, txt, url) => `<a href="${url}">${txt}</a>`);
  return t;
}

function htmlEscape(s) {
  return String(s === undefined || s === null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

const CSS = `
:root{--gold:#d4af37;--gold2:#e6c869;--champ:#f0e0b8;--copper:#b87333;}
body{font-family:"Segoe UI","Microsoft JhengHei",sans-serif;line-height:1.55;padding:0 22px 40px;color:var(--vscode-foreground);}
.hd{position:sticky;top:0;background:var(--vscode-editor-background);display:flex;justify-content:space-between;align-items:center;padding:14px 0;border-bottom:1px solid var(--vscode-panel-border);z-index:5;}
.hd__name{font-size:22px;font-weight:700;background:linear-gradient(90deg,var(--gold),var(--champ),var(--copper));-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;}
.hd__cat{color:var(--vscode-descriptionForeground);font-size:13px;margin-left:6px;}
#exp{background:linear-gradient(180deg,var(--gold),var(--copper));color:#1a160f;border:none;border-radius:6px;padding:7px 13px;font-weight:600;cursor:pointer;}
.meta{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0;}
.bdg{font-size:12px;background:var(--vscode-editorWidget-background);border:1px solid var(--vscode-panel-border);border-radius:14px;padding:3px 10px;}
.bdg i{color:var(--gold2);font-style:normal;margin-right:5px;}
.ovw{font-size:14px;}
h2{color:var(--gold2);border-bottom:1px solid var(--vscode-panel-border);padding-bottom:5px;margin-top:26px;font-size:16px;}
.md pre{background:var(--vscode-textCodeBlock-background);padding:12px;border-radius:8px;overflow:auto;}
.md code,code{font-family:"Cascadia Code",Consolas,monospace;font-size:12.5px;}
:not(pre)>code{background:var(--vscode-textCodeBlock-background);padding:1px 5px;border-radius:4px;}
.cmp{border:1px solid var(--vscode-panel-border);border-radius:8px;padding:10px 14px;margin:10px 0;}
.cmp__name{font-weight:600;color:var(--champ);margin-bottom:4px;}
.cmp__pro b{color:#5fb878;}.cmp__con b{color:#d96d6d;}.cmp ul{margin:4px 0;}
.tl{border-left:2px solid var(--copper);padding:4px 0 10px 14px;position:relative;}
.tl__y{font-family:"Cascadia Code",monospace;color:var(--gold2);font-weight:700;margin-right:8px;}
.tl__d{color:var(--vscode-descriptionForeground);font-size:13px;margin-top:2px;}
a{color:var(--gold2);}
`;

module.exports = { activate, deactivate };
