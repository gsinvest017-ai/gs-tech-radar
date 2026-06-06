"""FastAPI application — all API routes + static file serving."""
import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

from intelligence import analyzer
from scanner import gh_scanner, metrics as metrics_collector
from scanner.tech_detector import (
    detect_from_cargo_toml,
    detect_from_file_list,
    detect_from_go_mod,
    detect_from_package_json,
    detect_from_pyproject,
    detect_from_requirements,
    merge_matches,
)
from storage import db

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_db()
    yield


app = FastAPI(title="GS Tech Radar", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


# ─── Repo endpoints ──────────────────────────────────────────────────────────

class AddRepoRequest(BaseModel):
    url: str
    auto_scan: bool = True  # set False to import metadata only, no tech scan


@app.get("/api/me")
async def current_user():
    """Return the currently authenticated gh CLI username."""
    user = gh_scanner.get_current_gh_user()
    return {"login": user}


@app.post("/api/repos")
async def add_repo(req: AddRepoRequest, bg: BackgroundTasks):
    url = req.url.strip()

    # If input has no '/', treat it as a bare repo name and prepend current gh user
    if url and "/" not in url.lstrip("https://").lstrip("http://"):
        owner = gh_scanner.get_current_gh_user()
        if not owner:
            raise HTTPException(400, "Cannot detect logged-in gh user. Use owner/repo format instead.")
        url = f"{owner}/{url}"

    try:
        owner, repo_name = gh_scanner.parse_repo_url(url)
    except ValueError as e:
        raise HTTPException(400, str(e))

    canonical = f"https://github.com/{owner}/{repo_name}"
    existing = await db.get_repo_by_url(canonical)
    if existing:
        if req.auto_scan and not existing.get("last_scanned"):
            bg.add_task(_run_full_scan, existing["id"], owner, repo_name)
            return {"id": existing["id"], "status": "scanning"}
        return {"id": existing["id"], "status": "exists"}

    # Fetch basic info first (fast)
    info = await gh_scanner.fetch_repo_info(owner, repo_name)
    if not info:
        raise HTTPException(404, f"Repo {owner}/{repo_name} not found or not accessible")

    repo_id = await db.upsert_repo(info)
    if req.auto_scan:
        bg.add_task(_run_full_scan, repo_id, owner, repo_name)
        return {"id": repo_id, "status": "scanning"}
    return {"id": repo_id, "status": "imported"}


@app.post("/api/import-owner/{owner}")
async def import_owner_repos(owner: str):
    """Fetch all repos for owner and upsert metadata — no scan triggered."""
    repo_list = await gh_scanner.fetch_owner_repos(owner)
    imported = 0
    skipped = 0
    for info in repo_list:
        existing = await db.get_repo_by_url(info["url"])
        if existing:
            skipped += 1
            continue
        await db.upsert_repo(info)
        imported += 1
    return {"owner": owner, "total": len(repo_list), "imported": imported, "skipped": skipped}


@app.get("/api/repos")
async def list_repos():
    repos = await db.list_repos()
    result = []
    for r in repos:
        m = await db.get_metrics(r["id"])
        techs = await db.list_techs_for_repo(r["id"])
        scan_status = await db.latest_scan_status(r["id"])
        result.append({
            **r,
            "metrics": m or {},
            "tech_count": len(techs),
            "scan_status": scan_status.get("status") if scan_status else "none",
        })
    return result


@app.get("/api/repos/{repo_id}")
async def get_repo(repo_id: int):
    r = await db.get_repo(repo_id)
    if not r:
        raise HTTPException(404, "Repo not found")
    m = await db.get_metrics(repo_id)
    techs = await db.list_techs_for_repo(repo_id)
    return {**r, "metrics": m or {}, "techs": techs}


@app.delete("/api/repos/{repo_id}")
async def delete_repo(repo_id: int):
    await db.delete_repo(repo_id)
    return {"ok": True}


@app.post("/api/repos/{repo_id}/scan")
async def rescan_repo(repo_id: int, bg: BackgroundTasks):
    r = await db.get_repo(repo_id)
    if not r:
        raise HTTPException(404, "Repo not found")
    bg.add_task(_run_full_scan, repo_id, r["owner"], r["name"])
    return {"status": "scanning"}


@app.get("/api/repos/{repo_id}/techs")
async def repo_techs(repo_id: int):
    return await db.list_techs_for_repo(repo_id)


@app.get("/api/repos/{repo_id}/status")
async def repo_status(repo_id: int):
    s = await db.latest_scan_status(repo_id)
    return s or {"status": "none"}


# ─── Tech endpoints ──────────────────────────────────────────────────────────

@app.get("/api/techs")
async def list_techs():
    return await db.list_techs()


@app.get("/api/techs/{tech_name}/analysis")
async def tech_analysis(tech_name: str):
    techs = await db.list_techs()
    tech = next((t for t in techs if t["name"].lower() == tech_name.lower()), None)
    if not tech:
        raise HTTPException(404, f"Tech {tech_name!r} not found in DB")
    result = await analyzer.get_or_generate(tech["id"], tech["name"], tech["category"])
    return result


@app.post("/api/techs/{tech_name}/regenerate")
async def regenerate_tech(tech_name: str, bg: BackgroundTasks):
    techs = await db.list_techs()
    tech = next((t for t in techs if t["name"].lower() == tech_name.lower()), None)
    if not tech:
        raise HTTPException(404, f"Tech {tech_name!r} not found")
    bg.add_task(_regenerate_tech_analysis, tech["id"], tech["name"], tech["category"])
    return {"status": "generating"}


@app.get("/api/kg")
async def knowledge_graph(techs: str = ""):
    """Return merged KG for selected tech names (comma-separated)."""
    requested = [t.strip() for t in techs.split(",") if t.strip()]
    all_techs = await db.list_techs()
    if requested:
        selected = [(t["id"], t["name"], t["category"]) for t in all_techs if t["name"] in requested]
    else:
        selected = [(t["id"], t["name"], t["category"]) for t in all_techs]
    return await analyzer.get_merged_kg(selected)


@app.get("/api/dashboard")
async def dashboard_summary():
    repos = await db.list_repos()
    techs = await db.list_techs()

    total_commits = 0
    total_prs = 0
    total_contributors = 0
    total_stars = 0
    total_forks = 0

    for r in repos:
        total_stars += r.get("stars", 0)
        total_forks += r.get("forks", 0)
        m = await db.get_metrics(r["id"])
        if m:
            total_commits += m.get("commits_total", 0)
            total_prs += m.get("prs_merged", 0)
            total_contributors += m.get("contributors_count", 0)

    # Tech category breakdown
    cat_counts: dict[str, int] = {}
    for t in techs:
        cat = t["category"]
        cat_counts[cat] = cat_counts.get(cat, 0) + 1

    return {
        "repo_count": len(repos),
        "tech_count": len(techs),
        "total_commits": total_commits,
        "total_prs": total_prs,
        "total_contributors": total_contributors,
        "total_stars": total_stars,
        "total_forks": total_forks,
        "category_breakdown": [{"category": k, "count": v} for k, v in sorted(cat_counts.items(), key=lambda x: -x[1])],
    }


# ─── Background tasks ─────────────────────────────────────────────────────────

async def _run_full_scan(repo_id: int, owner: str, repo_name: str) -> None:
    log_id = await db.create_scan_log(repo_id)
    try:
        # Fetch manifests and file tree in parallel
        manifests, file_tree = await asyncio.gather(
            gh_scanner.fetch_manifest_files(owner, repo_name),
            gh_scanner.fetch_file_tree(owner, repo_name),
        )

        # Detect techs
        matches_groups = []
        if "requirements.txt" in manifests:
            matches_groups.append(detect_from_requirements(manifests["requirements.txt"]))
        if "pyproject.toml" in manifests:
            matches_groups.append(detect_from_pyproject(manifests["pyproject.toml"]))
        if "package.json" in manifests:
            matches_groups.append(detect_from_package_json(manifests["package.json"]))
        if "go.mod" in manifests:
            matches_groups.append(detect_from_go_mod(manifests["go.mod"]))
        if "Cargo.toml" in manifests:
            matches_groups.append(detect_from_cargo_toml(manifests["Cargo.toml"]))
        if file_tree:
            matches_groups.append(detect_from_file_list(file_tree))

        all_matches = merge_matches(matches_groups)

        # Persist techs
        for match in all_matches:
            tech_id = await db.upsert_tech(match.name, match.category)
            await db.upsert_repo_tech(repo_id, tech_id, match.version or "", match.source_file, match.confidence)

        # Collect metrics
        m = await metrics_collector.collect(owner, repo_name)
        await db.upsert_metrics(repo_id, m)
        await db.mark_repo_scanned(repo_id)
        await db.finish_scan_log(log_id, "done", f"Found {len(all_matches)} technologies")
    except Exception as exc:
        await db.finish_scan_log(log_id, "error", str(exc))


async def _regenerate_tech_analysis(tech_id: int, name: str, category: str) -> None:
    try:
        analysis = await analyzer.generate_analysis(name, category)
        await db.save_tech_analysis(tech_id, analysis)
    except Exception:
        pass
