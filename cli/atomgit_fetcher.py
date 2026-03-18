"""AtomGit URL parsing and content fetching for PR code review."""

import re
from typing import Literal

import httpx

from cr.config import ATOMGIT_TOKEN, ATOMGIT_API_BASE, GITCODE_API_BASE


UrlType = Literal["pr", "issue"]
PlatformType = Literal["github", "atomgit", "gitcode"]


def parse_atomgit_url(url: str) -> tuple[str, str, int, UrlType]:
    """Parse an AtomGit or GitCode URL into (owner, repo, number, type).

    Args:
        url: AtomGit/GitCode Issue or PR URL

    Returns:
        Tuple of (owner, repo, number, type)

    Raises:
        ValueError: If URL format is invalid

    Examples:
        >>> parse_atomgit_url("https://atomgit.com/owner/repo/pulls/123")
        ('owner', 'repo', 123, 'pr')
        >>> parse_atomgit_url("https://gitcode.com/owner/repo/pull/456")
        ('owner', 'repo', 456, 'pr')
        >>> parse_atomgit_url("https://atomgit.com/owner/repo/issues/789")
        ('owner', 'repo', 789, 'issue')
    """
    patterns = [
        (r"atomgit\.com/([^/]+)/([^/]+)/pulls?/(\d+)", "pr"),
        (r"gitcode\.com/([^/]+)/([^/]+)/pulls?/(\d+)", "pr"),
        (r"atomgit\.com/([^/]+)/([^/]+)/issues/(\d+)", "issue"),
        (r"gitcode\.com/([^/]+)/([^/]+)/issues/(\d+)", "issue"),
    ]

    for pattern, url_type in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1), match.group(2), int(match.group(3)), url_type

    raise ValueError(
        f"Invalid AtomGit/GitCode URL: {url}\n"
        "Expected format: https://atomgit.com/owner/repo/pulls/123 or "
        "https://gitcode.com/owner/repo/pull/123"
    )


def _get_headers() -> dict[str, str]:
    """Get HTTP headers for AtomGit/GitCode API requests."""
    headers = {
        "Accept": "application/json",
        "User-Agent": "asyncreview-atomgit",
        "Content-Type": "application/json",
    }
    if ATOMGIT_TOKEN:
        headers["private-token"] = ATOMGIT_TOKEN
    return headers


def _get_api_base(url: str) -> str:
    """Get API base URL based on the URL domain."""
    if "gitcode.com" in url:
        return GITCODE_API_BASE
    return ATOMGIT_API_BASE


async def fetch_pr(owner: str, repo: str, number: int, url: str = "") -> dict:
    """Fetch PR with full code review context from AtomGit/GitCode.

    Returns dict with:
        - metadata: title, body, author, state, etc.
        - files: list of changed files with patches
        - commits: commit history
        - comments: PR discussion comments
    """
    api_base = _get_api_base(url) if url else ATOMGIT_API_BASE

    async with httpx.AsyncClient() as client:
        pr_resp = await client.get(
            f"{api_base}/api/v5/repos/{owner}/{repo}/pulls/{number}",
            headers=_get_headers(),
            timeout=30.0,
        )
        pr_resp.raise_for_status()
        pr_data = pr_resp.json()

        files_resp = await client.get(
            f"{api_base}/api/v5/repos/{owner}/{repo}/pulls/{number}/files",
            headers=_get_headers(),
            params={"per_page": 100},
            timeout=30.0,
        )
        files_resp.raise_for_status()
        files_data = files_resp.json()

        commits_resp = await client.get(
            f"{api_base}/api/v5/repos/{owner}/{repo}/pulls/{number}/commits",
            headers=_get_headers(),
            params={"per_page": 100},
            timeout=30.0,
        )
        commits_list = []
        if commits_resp.status_code == 200:
            commits_data = commits_resp.json()
            commits_list = [
                {
                    "sha": c.get("sha", "")[:7] if c.get("sha") else "",
                    "message": c.get("commit", {}).get("message", "").split("\n")[0],
                    "author": c.get("commit", {}).get("author", {}).get("name", ""),
                }
                for c in commits_data
            ]

        comments_resp = await client.get(
            f"{api_base}/api/v5/repos/{owner}/{repo}/pulls/{number}/comments",
            headers=_get_headers(),
            params={"per_page": 50},
            timeout=30.0,
        )
        comments_list = []
        if comments_resp.status_code == 200:
            comments_data = comments_resp.json()
            comments_list = [
                {
                    "author": c.get("user", {}).get("login", ""),
                    "body": c.get("body", ""),
                }
                for c in comments_data
            ]

    files = _parse_files_data(files_data)

    return {
        "type": "pr",
        "platform": "atomgit",
        "owner": owner,
        "repo": repo,
        "number": number,
        "title": pr_data.get("title", ""),
        "body": pr_data.get("body") or "",
        "author": pr_data.get("user", {}).get("login", ""),
        "state": pr_data.get("state", "open"),
        "base_branch": pr_data.get("base", {}).get("ref", ""),
        "head_branch": pr_data.get("head", {}).get("ref", ""),
        "files": files,
        "commits": commits_list,
        "comments": comments_list,
        "additions": pr_data.get("additions", 0),
        "deletions": pr_data.get("deletions", 0),
        "changed_files_count": pr_data.get("changed_files", 0),
    }


def _parse_files_data(files_data: list[dict]) -> list[dict]:
    """Parse AtomGit files response into standard format."""
    files = []
    for f in files_data:
        patch_content = ""
        patch_obj = f.get("patch")
        if patch_obj:
            if isinstance(patch_obj, dict):
                patch_content = patch_obj.get("diff", "")
            elif isinstance(patch_obj, str):
                patch_content = patch_obj

        files.append(
            {
                "path": f.get("filename", ""),
                "status": f.get("status", "modified"),
                "additions": f.get("additions", 0),
                "deletions": f.get("deletions", 0),
                "patch": patch_content,
            }
        )
    return files


async def fetch_issue(owner: str, repo: str, number: int, url: str = "") -> dict:
    """Fetch issue content and comments from AtomGit/GitCode."""
    api_base = _get_api_base(url) if url else ATOMGIT_API_BASE

    async with httpx.AsyncClient() as client:
        issue_resp = await client.get(
            f"{api_base}/api/v5/repos/{owner}/{repo}/issues/{number}",
            headers=_get_headers(),
            timeout=30.0,
        )
        issue_resp.raise_for_status()
        issue_data = issue_resp.json()

        comments_resp = await client.get(
            f"{api_base}/api/v5/repos/{owner}/{repo}/issues/{number}/comments",
            headers=_get_headers(),
            params={"per_page": 50},
            timeout=30.0,
        )
        comments_list = []
        if comments_resp.status_code == 200:
            comments_data = comments_resp.json()
            comments_list = [
                {
                    "author": c.get("user", {}).get("login", ""),
                    "body": c.get("body", ""),
                }
                for c in comments_data
            ]

    return {
        "type": "issue",
        "platform": "atomgit",
        "owner": owner,
        "repo": repo,
        "number": number,
        "title": issue_data.get("title", ""),
        "body": issue_data.get("body") or "",
        "author": issue_data.get("user", {}).get("login", ""),
        "state": issue_data.get("state", "open"),
        "labels": [l.get("name", "") for l in issue_data.get("labels", [])],
        "comments": comments_list,
    }


def build_pr_context(data: dict) -> str:
    """Build a structured text representation of an AtomGit PR for RLM input."""
    lines = [
        f"# Pull Request: {data['title']}",
        f"",
        f"**Platform:** AtomGit",
        f"**Repository:** {data['owner']}/{data['repo']}",
        f"**Author:** {data['author']}",
        f"**Branch:** {data['head_branch']} → {data['base_branch']}",
        f"**Changes:** +{data['additions']} -{data['deletions']} across {data['changed_files_count']} files",
        f"",
    ]

    if data["body"]:
        lines.extend(
            [
                "## Description",
                "",
                data["body"],
                "",
            ]
        )

    if data["commits"]:
        lines.extend(
            [
                "## Commits",
                "",
            ]
        )
        for commit in data["commits"]:
            lines.append(f"- `{commit['sha']}` {commit['message']} ({commit['author']})")
        lines.append("")

    lines.extend(
        [
            "## Changed Files",
            "",
        ]
    )

    for file in data["files"]:
        status_icon = {"added": "+", "removed": "-", "modified": "~"}.get(file["status"], "~")
        lines.append(f"### [{status_icon}] {file['path']}")
        lines.append(f"*+{file['additions']} -{file['deletions']}*")
        lines.append("")

        if file["patch"]:
            lines.append("```diff")
            lines.append(file["patch"])
            lines.append("```")
            lines.append("")

    if data["comments"]:
        lines.extend(
            [
                "## Discussion",
                "",
            ]
        )
        for comment in data["comments"]:
            lines.append(f"**{comment['author']}:**")
            lines.append(comment["body"])
            lines.append("")

    return "\n".join(lines)


def build_issue_context(data: dict) -> str:
    """Build a text representation of an AtomGit issue for RLM input."""
    lines = [
        f"# Issue: {data['title']}",
        f"",
        f"**Platform:** AtomGit",
        f"**Repository:** {data['owner']}/{data['repo']}",
        f"**Author:** {data['author']}",
        f"**State:** {data['state']}",
    ]

    if data["labels"]:
        lines.append(f"**Labels:** {', '.join(data['labels'])}")

    lines.append("")

    if data["body"]:
        lines.extend(
            [
                "## Description",
                "",
                data["body"],
                "",
            ]
        )

    if data["comments"]:
        lines.extend(
            [
                "## Discussion",
                "",
            ]
        )
        for comment in data["comments"]:
            lines.append(f"**{comment['author']}:**")
            lines.append(comment["body"])
            lines.append("")

    return "\n".join(lines)


def build_review_context(data: dict) -> str:
    """Build a structured text representation for RLM input."""
    if data["type"] == "pr":
        return build_pr_context(data)
    else:
        return build_issue_context(data)
