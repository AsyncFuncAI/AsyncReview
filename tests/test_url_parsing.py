"""Regression tests for PR/issue URL parsing across forges."""

import pytest
from cli.github_fetcher import parse_github_url
from cr.github import parse_pr_url


# --- parse_github_url (cli) ---

@pytest.mark.parametrize("url,expected", [
    # GitHub
    ("https://github.com/owner/repo/pull/35", ("owner", "repo", 35, "pr")),
    ("https://github.com/owner/repo/pull/1?tab=files", ("owner", "repo", 1, "pr")),
    ("https://github.com/owner/repo/pull/1/", ("owner", "repo", 1, "pr")),
    # Gitea
    ("https://gitea.example.com/org/repo/pulls/42", ("org", "repo", 42, "pr")),
    ("https://gitea.example.com/org/my-project/pulls/1#issuecomment-20", ("org", "my-project", 1, "pr")),
    # GitLab
    ("https://gitlab.com/org/repo/-/merge_requests/10", ("org", "repo", 10, "pr")),
    ("https://gitlab.com/org/repo/-/merge_requests/10#note_123", ("org", "repo", 10, "pr")),
    # Bitbucket
    ("https://bitbucket.org/org/repo/pull-requests/5", ("org", "repo", 5, "pr")),
    ("https://bitbucket.org/org/repo/pull-requests/5?t=1", ("org", "repo", 5, "pr")),
    # Issues
    ("https://github.com/owner/repo/issues/1", ("owner", "repo", 1, "issue")),
    ("https://gitea.example.com/org/repo/issues/99", ("org", "repo", 99, "issue")),
    ("https://gitlab.com/org/repo/-/issues/7", ("org", "repo", 7, "issue")),
])
def test_parse_github_url(url, expected):
    assert parse_github_url(url) == expected


@pytest.mark.parametrize("url", [
    "https://github.com/owner/repo",
    "https://github.com/owner/repo/tree/main",
    "not-a-url",
    "",
])
def test_parse_github_url_invalid(url):
    with pytest.raises(ValueError):
        parse_github_url(url)


# --- parse_pr_url (cr) ---

@pytest.mark.parametrize("url,expected", [
    ("https://github.com/o/r/pull/1", ("o", "r", 1)),
    ("https://gitea.example.com/org/repo/pulls/42", ("org", "repo", 42)),
    ("https://gitlab.com/org/repo/-/merge_requests/10", ("org", "repo", 10)),
    ("https://bitbucket.org/org/repo/pull-requests/5", ("org", "repo", 5)),
    ("https://github.com/o/r/pull/1?tab=files#diff", ("o", "r", 1)),
])
def test_parse_pr_url(url, expected):
    assert parse_pr_url(url) == expected


@pytest.mark.parametrize("url", [
    "https://github.com/owner/repo/issues/1",
    "https://github.com/owner/repo",
    "garbage",
])
def test_parse_pr_url_invalid(url):
    with pytest.raises(ValueError):
        parse_pr_url(url)
