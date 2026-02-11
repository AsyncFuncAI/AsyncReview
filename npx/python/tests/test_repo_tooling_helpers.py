"""Unit tests for RepoTools and LocalRepoTools helper methods."""

import asyncio
import tempfile
from pathlib import Path

from cli.local_repo_tools import LocalRepoTools
from cli.repo_tools import RepoTools


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text="", headers=None):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}
        self.text = text
        self.headers = headers if headers is not None else {}

    def json(self):
        return self._json_data


class FakeAsyncClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append({"url": url, "params": params or {}, "headers": headers or {}, "timeout": timeout})
        if not self._responses:
            return FakeResponse(200, {"items": []})
        return self._responses.pop(0)


def test_repo_get_symbol_definition_uses_non_regex_queries():
    async def _run():
        tools = RepoTools("owner", "repo", "abcdef123456")
        fake_client = FakeAsyncClient(
            [
                FakeResponse(200, {"items": []}),
                FakeResponse(
                    200,
                    {
                        "items": [
                            {
                                "path": "src/example.py",
                                "text_matches": [{"fragment": "class MySymbol(BaseClass):"}],
                            }
                        ]
                    },
                ),
            ]
        )

        async def fake_get_client():
            return fake_client

        tools._get_client = fake_get_client  # type: ignore[method-assign]

        result = await tools.get_symbol_definition("MySymbol", "src/current_file.py")

        assert "Found in: src/example.py" in result
        queries = [call["params"].get("q", "") for call in fake_client.calls]
        assert any("def MySymbol" in q for q in queries)
        assert any("class MySymbol" in q for q in queries)
        assert all("|" not in q for q in queries)

    asyncio.run(_run())


def test_repo_find_usages_formats_results():
    async def _run():
        tools = RepoTools("owner", "repo", "abcdef123456")
        fake_client = FakeAsyncClient(
            [
                FakeResponse(
                    200,
                    {
                        "items": [
                            {"path": "src/a.py"},
                            {"path": "src/b.py"},
                        ]
                    },
                )
            ]
        )

        async def fake_get_client():
            return fake_client

        tools._get_client = fake_get_client  # type: ignore[method-assign]

        result = await tools.find_usages("my_symbol", "src")

        assert "Found 2 usages of 'my_symbol'" in result
        assert "src/a.py" in result
        assert "src/b.py" in result

    asyncio.run(_run())


def test_repo_get_call_graph_uses_literal_call_query():
    async def _run():
        tools = RepoTools("owner", "repo", "abcdef123456")
        fake_client = FakeAsyncClient([FakeResponse(200, {"items": []})])

        async def fake_get_client():
            return fake_client

        async def fake_outgoing(_func_name):
            return []

        tools._get_client = fake_get_client  # type: ignore[method-assign]
        tools._get_outgoing_calls = fake_outgoing  # type: ignore[method-assign]

        result = await tools.get_call_graph("my_func", depth=1)

        assert "Call graph for 'my_func'" in result
        query = fake_client.calls[0]["params"].get("q", "")
        assert "\"my_func(\"" in query
        assert "repo:owner/repo" in query

    asyncio.run(_run())


def test_repo_get_blame_filters_line_range():
    async def _run():
        tools = RepoTools("owner", "repo", "abcdef123456")
        commits_resp = FakeResponse(
            200,
            [
                {"sha": "abc1111", "commit": {"author": {"name": "A"}, "message": "touch lines"}},
                {"sha": "def2222", "commit": {"author": {"name": "B"}, "message": "other lines"}},
            ],
        )
        commit_a_resp = FakeResponse(
            200,
            {"files": [{"filename": "src/file.py", "patch": "@@ -1,2 +10,5 @@\n+line"}]},
        )
        commit_b_resp = FakeResponse(
            200,
            {"files": [{"filename": "src/file.py", "patch": "@@ -1,2 +50,2 @@\n+line"}]},
        )
        fake_client = FakeAsyncClient([commits_resp, commit_a_resp, commit_b_resp])

        async def fake_get_client():
            return fake_client

        tools._get_client = fake_get_client  # type: ignore[method-assign]

        result = await tools.get_blame("src/file.py", "10-12")

        assert "Blame for src/file.py (lines 10-12)" in result
        assert "abc1111"[:7] in result
        assert "def2222"[:7] not in result

    asyncio.run(_run())


def test_repo_get_commit_history_and_related_issues():
    async def _run():
        tools = RepoTools("owner", "repo", "abcdef123456")
        fake_client = FakeAsyncClient(
            [
                FakeResponse(
                    200,
                    [
                        {
                            "sha": "111aaaa",
                            "commit": {
                                "author": {"name": "Dev", "date": "2026-01-01T10:00:00Z"},
                                "message": "Refactor loader\n\nextra",
                            },
                        }
                    ],
                ),
                FakeResponse(
                    200,
                    {
                        "items": [
                            {"number": 12, "title": "Fix loader bug", "state": "open"},
                        ]
                    },
                ),
            ]
        )

        async def fake_get_client():
            return fake_client

        tools._get_client = fake_get_client  # type: ignore[method-assign]

        history = await tools.get_commit_history("src/file.py", limit=1)
        issues = await tools.get_related_issues("loader")

        assert "Commit history for src/file.py" in history
        assert "111aaaa"[:7] in history
        assert "Related issues for 'loader'" in issues
        assert "#12 [open] Fix loader bug" in issues

    asyncio.run(_run())


def test_local_get_symbol_definition_matches_class_and_def():
    async def _run():
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "pkg").mkdir()
            (root / "pkg" / "sample.py").write_text(
                "class MyClass:\n"
                "    pass\n\n"
                "def my_function():\n"
                "    return 1\n",
                encoding="utf-8",
            )

            tools = LocalRepoTools(str(root))
            class_result = await tools.get_symbol_definition("MyClass")
            func_result = await tools.get_symbol_definition("my_function", context_file="pkg/other.py")

            assert "local:pkg/sample.py" in class_result
            assert "local:pkg/sample.py" in func_result

    asyncio.run(_run())
