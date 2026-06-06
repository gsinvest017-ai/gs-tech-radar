"""Claude-powered technology intelligence generator.

Generates: overview, state-of-art, alternatives comparison,
cheatsheet (markdown), knowledge graph (nodes+edges), timeline (events).
All output cached in SQLite via storage.db.
"""
import json
import os
from typing import Optional

import anthropic

from storage import db

_client: Optional[anthropic.AsyncAnthropic] = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    return _client


_SYSTEM = """You are a technology intelligence analyst. You produce precise, structured JSON about software technologies.
Always respond with a single valid JSON object matching the schema given in the user message.
Be factual, concise, and use concrete version numbers and years where known."""

_PROMPT_TEMPLATE = """Analyse the technology: "{tech}" (category: {category})

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


async def generate_analysis(tech_name: str, category: str) -> dict:
    """Call Claude to generate full tech analysis. Returns parsed dict."""
    client = _get_client()
    prompt = _PROMPT_TEMPLATE.format(tech=tech_name, category=category)

    message = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    # Strip any accidental markdown fences
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

    return json.loads(raw)


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
