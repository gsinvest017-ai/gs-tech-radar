"""SQLite persistence layer — all tables, CRUD, and cache helpers."""
import json
import aiosqlite
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

DB_PATH = Path(__file__).parent.parent / "data" / "tech_radar.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS repos (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    url          TEXT UNIQUE NOT NULL,
    owner        TEXT NOT NULL,
    name         TEXT NOT NULL,
    description  TEXT,
    stars        INTEGER DEFAULT 0,
    forks        INTEGER DEFAULT 0,
    language     TEXT,
    topics       TEXT DEFAULT '[]',
    created_at   TEXT,
    updated_at   TEXT,
    last_scanned TEXT
);

CREATE TABLE IF NOT EXISTS techs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT UNIQUE NOT NULL,
    category     TEXT NOT NULL,
    year_created INTEGER,
    description  TEXT
);

CREATE TABLE IF NOT EXISTS repo_techs (
    repo_id     INTEGER,
    tech_id     INTEGER,
    version     TEXT,
    source_file TEXT,
    confidence  REAL DEFAULT 1.0,
    PRIMARY KEY (repo_id, tech_id),
    FOREIGN KEY (repo_id) REFERENCES repos(id) ON DELETE CASCADE,
    FOREIGN KEY (tech_id) REFERENCES techs(id)
);

CREATE TABLE IF NOT EXISTS tech_analysis (
    tech_id      INTEGER PRIMARY KEY,
    overview     TEXT,
    state_of_art TEXT,   -- JSON
    comparison   TEXT,   -- JSON
    cheatsheet   TEXT,   -- markdown
    kg_json      TEXT,   -- JSON {nodes, edges}
    timeline_json TEXT,  -- JSON {events}
    generated_at TEXT,
    FOREIGN KEY (tech_id) REFERENCES techs(id)
);

CREATE TABLE IF NOT EXISTS repo_metrics (
    repo_id            INTEGER PRIMARY KEY,
    commits_total      INTEGER DEFAULT 0,
    contributors_count INTEGER DEFAULT 0,
    prs_merged         INTEGER DEFAULT 0,
    issues_closed      INTEGER DEFAULT 0,
    lines_added        INTEGER DEFAULT 0,
    lines_removed      INTEGER DEFAULT 0,
    languages_json     TEXT DEFAULT '{}',
    scanned_at         TEXT,
    FOREIGN KEY (repo_id) REFERENCES repos(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS scan_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id    INTEGER,
    status     TEXT NOT NULL,  -- pending | running | done | error
    message    TEXT,
    started_at TEXT,
    ended_at   TEXT,
    FOREIGN KEY (repo_id) REFERENCES repos(id) ON DELETE CASCADE
);
"""


async def init_db() -> None:
    DB_PATH.parent.mkdir(exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(_SCHEMA)
        await db.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Repos ───────────────────────────────────────────────────────────────────

async def upsert_repo(data: dict) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("""
            INSERT INTO repos (url, owner, name, description, stars, forks, language, topics, created_at, updated_at)
            VALUES (:url, :owner, :name, :description, :stars, :forks, :language, :topics, :created_at, :updated_at)
            ON CONFLICT(url) DO UPDATE SET
                description=excluded.description, stars=excluded.stars, forks=excluded.forks,
                language=excluded.language, topics=excluded.topics, updated_at=excluded.updated_at
        """, {
            "url": data["url"], "owner": data["owner"], "name": data["name"],
            "description": data.get("description", ""),
            "stars": data.get("stars", 0), "forks": data.get("forks", 0),
            "language": data.get("language", ""), "topics": json.dumps(data.get("topics", [])),
            "created_at": data.get("created_at", ""), "updated_at": data.get("updated_at", ""),
        })
        await db.commit()
        cur = await db.execute("SELECT id FROM repos WHERE url=?", (data["url"],))
        row = await cur.fetchone()
        return row["id"]


async def mark_repo_scanned(repo_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE repos SET last_scanned=? WHERE id=?", (_now(), repo_id))
        await db.commit()


async def get_repo(repo_id: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM repos WHERE id=?", (repo_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_repo_by_url(url: str) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM repos WHERE url=?", (url,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def list_repos() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM repos ORDER BY updated_at DESC")
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def delete_repo(repo_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM repos WHERE id=?", (repo_id,))
        await db.commit()


# ── Techs ───────────────────────────────────────────────────────────────────

async def upsert_tech(name: str, category: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("""
            INSERT INTO techs (name, category)
            VALUES (?, ?)
            ON CONFLICT(name) DO UPDATE SET category=excluded.category
        """, (name, category))
        await db.commit()
        cur = await db.execute("SELECT id FROM techs WHERE name=?", (name,))
        row = await cur.fetchone()
        return row["id"]


async def upsert_repo_tech(repo_id: int, tech_id: int, version: str, source_file: str, confidence: float) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO repo_techs (repo_id, tech_id, version, source_file, confidence)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(repo_id, tech_id) DO UPDATE SET
                version=excluded.version, source_file=excluded.source_file, confidence=excluded.confidence
        """, (repo_id, tech_id, version, source_file, confidence))
        await db.commit()


async def list_techs() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("""
            SELECT t.*, COUNT(DISTINCT rt.repo_id) as repo_count
            FROM techs t
            LEFT JOIN repo_techs rt ON rt.tech_id = t.id
            GROUP BY t.id
            ORDER BY repo_count DESC, t.name
        """)
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def list_techs_for_repo(repo_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("""
            SELECT t.*, rt.version, rt.source_file, rt.confidence
            FROM techs t
            JOIN repo_techs rt ON rt.tech_id = t.id
            WHERE rt.repo_id = ?
            ORDER BY rt.confidence DESC, t.name
        """, (repo_id,))
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


# ── Tech analysis ────────────────────────────────────────────────────────────

async def get_tech_analysis(tech_id: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM tech_analysis WHERE tech_id=?", (tech_id,))
        row = await cur.fetchone()
        if not row:
            return None
        d = dict(row)
        for key in ("state_of_art", "comparison", "kg_json", "timeline_json"):
            if d.get(key):
                try:
                    d[key] = json.loads(d[key])
                except Exception:
                    pass
        return d


async def save_tech_analysis(tech_id: int, analysis: dict) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO tech_analysis (tech_id, overview, state_of_art, comparison, cheatsheet, kg_json, timeline_json, generated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(tech_id) DO UPDATE SET
                overview=excluded.overview, state_of_art=excluded.state_of_art,
                comparison=excluded.comparison, cheatsheet=excluded.cheatsheet,
                kg_json=excluded.kg_json, timeline_json=excluded.timeline_json,
                generated_at=excluded.generated_at
        """, (
            tech_id,
            analysis.get("overview", ""),
            json.dumps(analysis.get("state_of_art", {})),
            json.dumps(analysis.get("comparison", [])),
            analysis.get("cheatsheet", ""),
            json.dumps(analysis.get("kg_data", {})),
            json.dumps(analysis.get("timeline", {})),
            _now(),
        ))
        await db.commit()


# ── Repo metrics ─────────────────────────────────────────────────────────────

async def upsert_metrics(repo_id: int, m: dict) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO repo_metrics (repo_id, commits_total, contributors_count, prs_merged,
                issues_closed, lines_added, lines_removed, languages_json, scanned_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(repo_id) DO UPDATE SET
                commits_total=excluded.commits_total,
                contributors_count=excluded.contributors_count,
                prs_merged=excluded.prs_merged,
                issues_closed=excluded.issues_closed,
                lines_added=excluded.lines_added,
                lines_removed=excluded.lines_removed,
                languages_json=excluded.languages_json,
                scanned_at=excluded.scanned_at
        """, (
            repo_id, m.get("commits_total", 0), m.get("contributors_count", 0),
            m.get("prs_merged", 0), m.get("issues_closed", 0),
            m.get("lines_added", 0), m.get("lines_removed", 0),
            json.dumps(m.get("languages", {})), _now(),
        ))
        await db.commit()


async def get_metrics(repo_id: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM repo_metrics WHERE repo_id=?", (repo_id,))
        row = await cur.fetchone()
        if not row:
            return None
        d = dict(row)
        if d.get("languages_json"):
            try:
                d["languages"] = json.loads(d["languages_json"])
            except Exception:
                d["languages"] = {}
        return d


# ── Scan log ──────────────────────────────────────────────────────────────────

async def create_scan_log(repo_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "INSERT INTO scan_log (repo_id, status, started_at) VALUES (?, 'running', ?)",
            (repo_id, _now())
        )
        await db.commit()
        return cur.lastrowid


async def finish_scan_log(log_id: int, status: str, message: str = "") -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE scan_log SET status=?, message=?, ended_at=? WHERE id=?",
            (status, message, _now(), log_id)
        )
        await db.commit()


async def latest_scan_status(repo_id: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM scan_log WHERE repo_id=? ORDER BY id DESC LIMIT 1",
            (repo_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None
