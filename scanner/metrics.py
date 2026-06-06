"""Aggregate repo selling-point metrics into a unified dict."""
import asyncio

from scanner import gh_scanner


async def collect(owner: str, repo: str) -> dict:
    """Fetch all metrics in parallel and return a unified dict."""
    results = await asyncio.gather(
        gh_scanner.fetch_languages(owner, repo),
        gh_scanner.fetch_contributors_count(owner, repo),
        gh_scanner.fetch_commit_count(owner, repo),
        gh_scanner.fetch_pr_count(owner, repo),
        gh_scanner.fetch_issue_count(owner, repo),
        return_exceptions=True,
    )

    languages = results[0] if not isinstance(results[0], Exception) else {}
    contributors = results[1] if not isinstance(results[1], Exception) else 0
    commits = results[2] if not isinstance(results[2], Exception) else 0
    prs = results[3] if not isinstance(results[3], Exception) else 0
    issues = results[4] if not isinstance(results[4], Exception) else 0

    return {
        "languages": languages,
        "contributors_count": contributors,
        "commits_total": commits,
        "prs_merged": prs,
        "issues_closed": issues,
        "lines_added": 0,
        "lines_removed": 0,
    }
