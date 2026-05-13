"""Integration tests with real LLM API calls.

These tests require:
1. GEMINI_API_KEY, OPENAI_API_KEY, or ANTHROPIC_API_KEY in .env
2. GITHUB_TOKEN in .env (for public repo access)

Run with: uv run pytest tests/test_integration.py -v -s

Note: Tests are ordered carefully to avoid DSPy thread configuration conflicts.
The server test runs first (in its own thread via TestClient), then the direct
RLM tests run after.
"""

import os
import pytest

LLM_API_KEY_VARS = ("GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")

# Skip all tests if no API key
pytestmark = pytest.mark.skipif(
    not any(os.getenv(name) for name in LLM_API_KEY_VARS) and not os.path.exists(".env"),
    reason="No LLM API key set",
)


@pytest.fixture(scope="module")
def load_env():
    """Load .env file for tests."""
    from dotenv import load_dotenv
    load_dotenv()
    # Reset server singletons to ensure fresh state
    import cr.server
    cr.server._diff_qa_rlm = None
    cr.server._auto_review_rlm = None


class TestGitHubIntegration:
    """Test GitHub API integration with real API calls."""

    @pytest.mark.asyncio
    async def test_load_real_pr(self, load_env):
        """Test loading a real public PR from GitHub."""
        from cr.github import load_pr, get_file_contents

        # Use a well-known public PR (octocat/Hello-World)
        pr_url = "https://github.com/octocat/Hello-World/pull/1"

        pr_info = await load_pr(pr_url)

        assert pr_info is not None
        assert pr_info.owner == "octocat"
        assert pr_info.repo == "Hello-World"
        assert pr_info.number == 1
        assert len(pr_info.files) > 0

        # Test getting file contents (files are dicts with 'path' key)
        first_file = pr_info.files[0]
        old_file, new_file = await get_file_contents(pr_info.review_id, first_file["path"])

        # At least one should exist (modified files have both, added have only new, deleted have only old)
        assert old_file is not None or new_file is not None


class TestServerIntegration:
    """Test the full server flow with real API calls."""

    @pytest.mark.asyncio
    async def test_full_flow(self, load_env):
        """Test the full flow: load PR -> ask question -> get streaming response."""
        from fastapi.testclient import TestClient
        from cr.server import app
        
        client = TestClient(app)
        
        # 1. Load a PR
        response = client.post(
            "/api/github/load_pr",
            json={"prUrl": "https://github.com/octocat/Hello-World/pull/1"}
        )
        assert response.status_code == 200
        pr_info = response.json()
        review_id = pr_info["reviewId"]
        
        print(f"\n--- Loaded PR ---")
        print(f"Review ID: {review_id}")
        print(f"Title: {pr_info['title']}")
        print(f"Files: {[f['path'] for f in pr_info['files']]}")
        
        # 2. Get file contents
        if pr_info["files"]:
            response = client.get(
                "/api/github/file",
                params={"reviewId": review_id, "path": pr_info["files"][0]["path"]}
            )
            assert response.status_code == 200
            file_contents = response.json()
            print(f"\n--- File Contents ---")
            print(f"Old file: {file_contents['oldFile'] is not None}")
            print(f"New file: {file_contents['newFile'] is not None}")
        
        # 3. Ask a question (non-streaming for simpler test)
        response = client.post(
            "/api/diff/ask",
            json={
                "reviewId": review_id,
                "question": "Summarize this PR in one sentence",
                "conversation": [],
                "selection": None,
            }
        )
        if response.status_code != 200:
            print(f"\n--- Error Response ---")
            print(f"Status: {response.status_code}")
            print(f"Body: {response.text}")
        assert response.status_code == 200
        answer = response.json()
        
        print(f"\n--- Answer ---")
        for block in answer["answerBlocks"]:
            print(f"[{block['type']}]: {block['content'][:200]}...")
        
        assert len(answer["answerBlocks"]) > 0
