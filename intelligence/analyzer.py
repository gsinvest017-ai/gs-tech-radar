"""Claude Code CLI-powered technology intelligence generator.

Uses `claude --print` (Claude Code CLI) — no API key required, runs under the
user's existing Claude Code session.

Generates: overview, state-of-art, alternatives comparison,
cheatsheet (markdown), knowledge graph (nodes+edges), timeline (events).
All output cached in SQLite via storage.db.
"""
import asyncio
import concurrent.futures
import json
import shutil
import subprocess
import sys
from typing import Optional

from storage import db

# Resolve `claude` binary at import time
_CLAUDE_BIN: str = shutil.which("claude") or ("claude.cmd" if sys.platform == "win32" else "claude")

# Thread pool for blocking subprocess calls (avoids Windows asyncio subprocess issues)
_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=3, thread_name_prefix="claude-worker")


def _run_claude_sync(prompt_bytes: bytes, timeout: int) -> str:
    """Synchronous wrapper — runs in a thread pool to stay non-blocking."""
    try:
        result = subprocess.run(
            [_CLAUDE_BIN, "--print", "--output-format", "json"],
            input=prompt_bytes,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"claude CLI timed out after {timeout}s")
    except FileNotFoundError:
        raise RuntimeError(f"claude CLI not found at {_CLAUDE_BIN!r}. Make sure Claude Code is installed and on PATH.")
    except Exception as exc:
        raise RuntimeError(f"claude CLI failed to start: {type(exc).__name__}: {exc}")

    if result.returncode != 0:
        err = result.stderr.decode("utf-8", errors="replace")[:600]
        raise RuntimeError(f"claude CLI exited {result.returncode}: {err or '(no stderr)'}")

    raw = result.stdout.decode("utf-8", errors="replace").strip()

    # claude --output-format json wraps the reply:
    # {"type":"result","result":"...actual text..."}
    try:
        envelope = json.loads(raw)
        if isinstance(envelope, dict) and "result" in envelope:
            return envelope["result"]
    except json.JSONDecodeError:
        pass

    return raw  # older CLI versions without JSON envelope


async def _call_claude(prompt: str, timeout: int = 120) -> str:
    """Call claude CLI in a thread pool to avoid asyncio subprocess issues on Windows."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_POOL, _run_claude_sync, prompt.encode("utf-8"), timeout)


_PROMPT_TEMPLATE = """You are a technology intelligence analyst. Produce ONLY a single valid JSON object — no prose, no markdown fences.

Analyse the technology: "{tech}" (category: {category})

Return a JSON object with EXACTLY these keys:

{{
  "overview": "2-3 sentence description of what this technology is and why it matters",
  "year_created": <integer year or null>,
  "creator": "person or team name",
  "organization": "backing org or null",
  "ecosystem_status": "thriving | stable | declining | niche",
  "current_version": "latest stable version string or null",
  "state_of_art": {{
    "headline": "one sentence on current state",
    "latest_features": ["feature 1", "feature 2", "feature 3"],
    "best_practices": ["practice 1", "practice 2", "practice 3"],
    "notable_users": ["org1", "org2", "org3"]
  }},
  "comparison": [
    {{
      "name": "alternative tech name",
      "pros_over_subject": ["advantage 1", "advantage 2"],
      "cons_over_subject": ["disadvantage 1", "disadvantage 2"],
      "best_for": "one sentence use case"
    }}
  ],
  "cheatsheet": "markdown string with ## sections: Installation, Quick Start, Common Patterns, Key Commands/APIs — include code blocks",
  "kg_data": {{
    "nodes": [
      {{"id": "string", "label": "string", "type": "tech|language|concept|org|person|standard", "description": "short string"}}
    ],
    "edges": [
      {{"source": "id", "target": "id", "type": "built_on|uses|created_by|sponsored_by|related_to|alternative_to|part_of"}}
    ]
  }},
  "timeline": {{
    "events": [
      {{"year": <int>, "type": "created|milestone|version|paradigm_shift", "title": "string", "description": "string"}}
    ]
  }}
}}

For kg_data: include the technology itself as a central node, plus its language(s), key concepts it uses or introduces,
the creator/org, and 2-3 alternative/related technologies as nodes. Edges should connect them meaningfully.

For comparison: include 3 alternatives from the same category.
For timeline: include at least 5 events from creation to present.
Return ONLY the JSON, no prose."""


def _extract_json(raw: str) -> dict:
    """Robustly extract a JSON object from raw text that may contain prose or fences."""
    raw = raw.strip()

    # Strip markdown code fences
    if raw.startswith("```"):
        lines = raw.split("\n")
        # drop first line (```json or ```) and trailing ```
        inner = "\n".join(lines[1:])
        inner = inner.rstrip("`").strip()
        raw = inner

    # Try direct parse first
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Find first '{' … last '}' — handles leading/trailing prose
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            pass

    raise ValueError(f"No valid JSON found in Claude output (first 200 chars): {raw[:200]!r}")


async def generate_analysis(tech_name: str, category: str) -> dict:
    """Call Claude Code CLI to generate full tech analysis. Returns parsed dict."""
    prompt = _PROMPT_TEMPLATE.format(tech=tech_name, category=category)
    raw = await _call_claude(prompt)
    return _extract_json(raw)


async def get_or_generate(tech_id: int, tech_name: str, category: str) -> dict:
    """Return cached analysis or generate fresh one."""
    cached = await db.get_tech_analysis(tech_id)
    if cached and cached.get("overview"):
        return cached

    analysis = await generate_analysis(tech_name, category)
    await db.save_tech_analysis(tech_id, analysis)
    return analysis


async def get_merged_kg(tech_ids_names: list[tuple[int, str, str]]) -> dict:
    """Merge knowledge graph data from multiple technologies."""
    all_nodes: dict[str, dict] = {}
    all_edges: list[dict] = []
    edge_set: set[tuple] = set()

    for tech_id, tech_name, category in tech_ids_names:
        cached = await db.get_tech_analysis(tech_id)
        if not cached or not cached.get("kg_json"):
            continue
        kg = cached["kg_json"]
        if isinstance(kg, str):
            try:
                kg = json.loads(kg)
            except Exception:
                continue
        for node in kg.get("nodes", []):
            nid = node.get("id", "")
            if nid and nid not in all_nodes:
                all_nodes[nid] = node
        for edge in kg.get("edges", []):
            key = (edge.get("source"), edge.get("target"), edge.get("type"))
            if key not in edge_set:
                edge_set.add(key)
                all_edges.append(edge)

    return {"nodes": list(all_nodes.values()), "edges": all_edges}
