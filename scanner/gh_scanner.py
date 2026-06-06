"""GitHub repo scanner — fetches metadata and manifest files via gh CLI / REST API."""
import asyncio
import base64
import json
import subprocess
from typing import Optional

import httpx


def _gh_token() -> str:
    try:
        result = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, timeout=10
        )
        token = result.stdout.strip()
        if token:
            return token
    except Exception:
        pass
    return ""


_CURRENT_USER: str = ""


def get_current_gh_user() -> str:
    """Return the currently authenticated gh CLI username (cached)."""
    global _CURRENT_USER
    if _CURRENT_USER:
        return _CURRENT_USER
    try:
        result = subprocess.run(
            ["gh", "api", "user", "--jq", ".login"],
            capture_output=True, text=True, timeout=10
        )
        user = result.stdout.strip()
        if user:
            _CURRENT_USER = user
            return user
    except Exception:
        pass
    return ""


_TOKEN: str = ""


def _headers() -> dict[str, str]:
    global _TOKEN
    if not _TOKEN:
        _TOKEN = _gh_token()
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if _TOKEN:
        h["Authorization"] = f"Bearer {_TOKEN}"
    return h


async def _get(client: httpx.AsyncClient, url: str) -> Optional[dict]:
    try:
        r = await client.get(url, headers=_headers(), timeout=20)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def parse_repo_url(url: str) -> tuple[str, str]:
    """Returns (owner, repo) from a GitHub URL or owner/repo string."""
    url = url.rstrip("/")
    # Handle full URLs
    for prefix in ("https://github.com/", "http://github.com/", "github.com/"):
        if url.startswith(prefix):
            url = url[len(prefix):]
            break
    url = url.replace(".git", "")
    parts = url.split("/")
    if len(parts) >= 2:
        return parts[0], parts[1]
    raise ValueError(f"Cannot parse repo URL: {url!r}")


async def fetch_owner_repos(owner: str, max_pages: int = 10) -> list[dict]:
    """Return metadata for all public repos owned by `owner` (up to max_pages×100)."""
    results: list[dict] = []
    async with httpx.AsyncClient() as client:
        for page in range(1, max_pages + 1):
            data = await _get(
                client,
                f"https://api.github.com/users/{owner}/repos"
                f"?per_page=100&page={page}&sort=pushed&type=owner",
            )
            if not data or not isinstance(data, list):
                break
            for r in data:
                repo_name = r.get("name", "")
                if not repo_name:
                    continue
                results.append({
                    "url": f"https://github.com/{owner}/{repo_name}",
                    "owner": owner,
                    "name": repo_name,
                    "description": r.get("description") or "",
                    "stars": r.get("stargazers_count", 0),
                    "forks": r.get("forks_count", 0),
                    "language": r.get("language") or "",
                    "topics": r.get("topics") or [],
                    "created_at": r.get("created_at", ""),
                    "updated_at": r.get("pushed_at", ""),
                })
            if len(data) < 100:
                break  # last page
    return results


async def fetch_repo_info(owner: str, repo: str) -> dict:
    async with httpx.AsyncClient() as client:
        data = await _get(client, f"https://api.github.com/repos/{owner}/{repo}")
        if not data:
            return {}
        return {
            "url": f"https://github.com/{owner}/{repo}",
            "owner": owner,
            "name": repo,
            "description": data.get("description", ""),
            "stars": data.get("stargazers_count", 0),
            "forks": data.get("forks_count", 0),
            "language": data.get("language", ""),
            "topics": data.get("topics", []),
            "created_at": data.get("created_at", ""),
            "updated_at": data.get("pushed_at", ""),
        }


async def fetch_languages(owner: str, repo: str) -> dict[str, int]:
    async with httpx.AsyncClient() as client:
        data = await _get(client, f"https://api.github.com/repos/{owner}/{repo}/languages")
        return data or {}


async def fetch_contributors_count(owner: str, repo: str) -> int:
    async with httpx.AsyncClient() as client:
        # Use stats/contributors for accurate count
        data = await _get(client, f"https://api.github.com/repos/{owner}/{repo}/contributors?per_page=100&anon=1")
        if isinstance(data, list):
            return len(data)
        return 0


async def fetch_commit_count(owner: str, repo: str) -> int:
    """Get approximate total commit count via the contributors stats endpoint."""
    async with httpx.AsyncClient() as client:
        data = await _get(client, f"https://api.github.com/repos/{owner}/{repo}/contributors?per_page=100&anon=1")
        if isinstance(data, list):
            return sum(c.get("contributions", 0) for c in data)
        return 0


async def fetch_pr_count(owner: str, repo: str) -> int:
    async with httpx.AsyncClient() as client:
        # Use search API for closed+merged PRs
        data = await _get(
            client,
            f"https://api.github.com/search/issues?q=repo:{owner}/{repo}+type:pr+is:merged&per_page=1"
        )
        if data and "total_count" in data:
            return data["total_count"]
        return 0


async def fetch_issue_count(owner: str, repo: str) -> int:
    async with httpx.AsyncClient() as client:
        data = await _get(
            client,
            f"https://api.github.com/search/issues?q=repo:{owner}/{repo}+type:issue+is:closed&per_page=1"
        )
        if data and "total_count" in data:
            return data["total_count"]
        return 0


async def _fetch_file_content(client: httpx.AsyncClient, owner: str, repo: str, path: str) -> Optional[str]:
    data = await _get(client, f"https://api.github.com/repos/{owner}/{repo}/contents/{path}")
    if data and isinstance(data, dict) and data.get("encoding") == "base64":
        try:
            return base64.b64decode(data["content"].replace("\n", "")).decode("utf-8", errors="replace")
        except Exception:
            pass
    return None


async def fetch_manifest_files(owner: str, repo: str) -> dict[str, str]:
    """Fetch key manifest/config files for tech detection."""
    candidates = [
        "requirements.txt",
        "pyproject.toml",
        "setup.py",
        "package.json",
        "go.mod",
        "Cargo.toml",
        "pom.xml",
        "build.gradle",
        "Dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
    ]
    async with httpx.AsyncClient() as client:
        tasks = {path: _fetch_file_content(client, owner, repo, path) for path in candidates}
        results: dict[str, str] = {}
        for path, coro in tasks.items():
            content = await coro
            if content:
                results[path] = content
        return results


async def fetch_file_tree(owner: str, repo: str, max_files: int = 500) -> list[str]:
    """Get top-level + one-level-deep file paths for infra detection."""
    async with httpx.AsyncClient() as client:
        data = await _get(
            client,
            f"https://api.github.com/repos/{owner}/{repo}/git/trees/HEAD?recursive=1"
        )
        if data and "tree" in data:
            return [item["path"] for item in data["tree"] if item.get("type") == "blob"][:max_files]
        return []


async def fetch_commit_code_stats(owner: str, repo: str, limit: int = 30) -> tuple[int, int]:
    """Sample recent commits and sum lines_added / lines_removed."""
    async with httpx.AsyncClient() as client:
        commits = await _get(
            client,
            f"https://api.github.com/repos/{owner}/{repo}/commits?per_page={limit}"
        )
        if not isinstance(commits, list):
            return 0, 0
        added = removed = 0
        for c in commits[:limit]:
            sha = c.get("sha", "")
            if not sha:
                continue
            detail = await _get(client, f"https://api.github.com/repos/{owner}/{repo}/commits/{sha}")
            if detail and "stats" in detail:
                added += detail["stats"].get("additions", 0)
                removed += detail["stats"].get("deletions", 0)
        return added, removed
