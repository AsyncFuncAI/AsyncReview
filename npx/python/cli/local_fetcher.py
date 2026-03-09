"""Local directory context building for code review."""

import os
import subprocess
from pathlib import Path
from typing import Optional


def validate_local_path(path: str) -> str:
    """Resolve and validate a local directory path.
    
    Args:
        path: Directory path (relative or absolute)
        
    Returns:
        Absolute path as string
        
    Raises:
        ValueError: If path doesn't exist or is not a directory
    """
    abs_path = os.path.abspath(os.path.expanduser(path))
    if not os.path.isdir(abs_path):
        raise ValueError(f"Path is not a valid directory: {path}")
    return abs_path


def is_git_repo(path: str) -> bool:
    """Check if a directory is a git repository.
    
    Args:
        path: Directory path
        
    Returns:
        True if .git exists or git rev-parse succeeds
    """
    git_dir = os.path.join(path, ".git")
    if os.path.exists(git_dir):
        return True
    
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def get_git_diff(path: str) -> Optional[str]:
    """Get git diff (staged + unstaged changes).
    
    Args:
        path: Directory path
        
    Returns:
        Combined diff string or None if not a git repo or no changes
    """
    if not is_git_repo(path):
        return None
    
    try:
        # Get unstaged changes
        unstaged = subprocess.run(
            ["git", "diff"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        
        # Get staged changes
        staged = subprocess.run(
            ["git", "diff", "--staged"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        
        diff_output = (staged.stdout + unstaged.stdout).strip()
        
        if not diff_output:
            return None
        
        # Truncate if exceeds 100KB
        if len(diff_output) > 100 * 1024:
            diff_output = diff_output[:100 * 1024] + "\n... (truncated)"
        
        return diff_output
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def get_git_info(path: str) -> Optional[dict]:
    """Get git repository information.
    
    Args:
        path: Directory path
        
    Returns:
        Dict with branch, commits, repo_name or None if not a git repo
    """
    if not is_git_repo(path):
        return None
    
    try:
        # Get branch name
        branch_result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "unknown"
        
        # Get recent commits
        commits_result = subprocess.run(
            ["git", "log", "--oneline", "-10"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        commits = commits_result.stdout.strip().split("\n") if commits_result.returncode == 0 else []
        
        # Get repo name from directory or git remote
        repo_name = os.path.basename(path)
        try:
            remote_result = subprocess.run(
                ["git", "config", "--get", "remote.origin.url"],
                cwd=path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if remote_result.returncode == 0:
                remote_url = remote_result.stdout.strip()
                # Extract repo name from URL
                repo_name = remote_url.split("/")[-1].replace(".git", "")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        
        return {
            "branch": branch,
            "commits": [c for c in commits if c],
            "repo_name": repo_name,
        }
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def get_project_structure(path: str, max_depth: int = 3, max_files: int = 200) -> str:
    """Generate a tree-like representation of the project structure.

    Args:
        path: Directory path
        max_depth: Maximum directory depth to traverse
        max_files: Maximum number of files to include

    Returns:
        Tree-like string representation
    """
    ignore_patterns = {
        ".git", "node_modules", "__pycache__", ".venv", "venv",
        ".env", "dist", "build", ".next", ".tox", ".pytest_cache",
        ".mypy_cache", ".coverage", "*.pyc", ".DS_Store", ".idea",
        ".vscode", "*.egg-info", ".gradle", "target", "out",
    }

    def should_ignore(name: str) -> bool:
        """Check if a file/dir should be ignored."""
        if name.startswith("."):
            return True
        for pattern in ignore_patterns:
            if pattern.startswith("*"):
                if name.endswith(pattern[1:]):
                    return True
            elif name == pattern:
                return True
        return False

    lines = []
    file_count = [0]  # Use list to allow modification in nested function

    def walk_tree(dir_path: str, prefix: str = "", depth: int = 0) -> None:
        """Recursively walk directory tree."""
        if depth > max_depth or file_count[0] >= max_files:
            return

        try:
            entries = sorted(os.listdir(dir_path))
        except (PermissionError, OSError):
            return

        dirs = []
        files = []

        for entry in entries:
            if should_ignore(entry):
                continue
            full_path = os.path.join(dir_path, entry)
            if os.path.isdir(full_path):
                dirs.append(entry)
            else:
                files.append(entry)

        # Process directories first
        for i, dir_name in enumerate(dirs):
            is_last_dir = (i == len(dirs) - 1) and len(files) == 0
            connector = "└── " if is_last_dir else "├── "
            lines.append(f"{prefix}{connector}{dir_name}/")

            if file_count[0] < max_files:
                next_prefix = prefix + ("    " if is_last_dir else "│   ")
                walk_tree(os.path.join(dir_path, dir_name), next_prefix, depth + 1)

        # Process files
        for i, file_name in enumerate(files):
            if file_count[0] >= max_files:
                break
            is_last = i == len(files) - 1
            connector = "└── " if is_last else "├── "
            lines.append(f"{prefix}{connector}{file_name}")
            file_count[0] += 1

    walk_tree(path)
    return "\n".join(lines) if lines else "(empty directory)"


def build_local_context(path: str) -> str:
    """Build a structured text context for local directory review.

    Args:
        path: Directory path

    Returns:
        Structured text context for RLM input
    """
    abs_path = validate_local_path(path)
    dir_name = os.path.basename(abs_path)

    lines = [
        f"# Local Repository Review: {dir_name}",
        "",
        f"**Path:** {abs_path}",
    ]

    # Get git info if available
    git_info = get_git_info(abs_path)
    if git_info:
        lines.extend([
            f"**Branch:** {git_info['branch']}",
            f"**Repository:** {git_info['repo_name']}",
            "",
        ])

        # Recent commits
        if git_info["commits"]:
            lines.extend([
                "## Recent Commits",
                "",
            ])
            for commit in git_info["commits"]:
                lines.append(f"- {commit}")
            lines.append("")

        # Git diff
        diff = get_git_diff(abs_path)
        if diff:
            lines.extend([
                "## Git Diff",
                "",
                "```diff",
                diff,
                "```",
                "",
            ])
    else:
        lines.append("**Status:** Not a git repository")
        lines.append("")

    # Project structure
    lines.extend([
        "## Project Structure",
        "",
        get_project_structure(abs_path),
        "",
    ])

    return "\n".join(lines)

