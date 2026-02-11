"""Tests for get_type_hierarchy function in repo_tools and local_repo_tools."""

import asyncio
import os
import tempfile
import pytest
from pathlib import Path

from cli.repo_tools import RepoTools
from cli.local_repo_tools import LocalRepoTools


class TestLocalRepoToolsTypeHierarchy:
    """Tests for LocalRepoTools.get_type_hierarchy with multi-line class definitions."""

    @pytest.fixture
    def temp_repo(self):
        """Create a temporary repository with test classes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a test Python file with multi-line class definition
            test_file = Path(tmpdir) / "test_classes.py"
            test_file.write_text("""
class GrandParent:
    pass

class Parent(
    GrandParent
):
    pass

class Child(
    Parent,
    object
):
    pass

class MultilineParent(
    GrandParent,
    object
):
    pass
""")
            yield tmpdir

    @pytest.mark.asyncio
    async def test_single_line_class(self, temp_repo):
        """Test parsing single-line class definition."""
        tools = LocalRepoTools(temp_repo)
        result = await tools.get_type_hierarchy("GrandParent")
        assert "GrandParent" in result
        assert "no parents" in result.lower()

    @pytest.mark.asyncio
    async def test_multiline_class_definition(self, temp_repo):
        """Test parsing multi-line class definition."""
        tools = LocalRepoTools(temp_repo)
        result = await tools.get_type_hierarchy("Parent")
        assert "Parent" in result
        assert "GrandParent" in result
        assert "extends" in result

    @pytest.mark.asyncio
    async def test_multiline_with_multiple_parents(self, temp_repo):
        """Test parsing multi-line class with multiple parents."""
        tools = LocalRepoTools(temp_repo)
        result = await tools.get_type_hierarchy("Child")
        assert "Child" in result
        assert "Parent" in result
        assert "object" in result

    @pytest.mark.asyncio
    async def test_parent_resolution(self, temp_repo):
        """Test one level of parent resolution."""
        tools = LocalRepoTools(temp_repo)
        result = await tools.get_type_hierarchy("Child")
        # Should show Child's parents and their parents
        assert "Parent details:" in result
        assert "Parent extends:" in result or "Parent (no parents found)" in result

    @pytest.mark.asyncio
    async def test_empty_class_name(self, temp_repo):
        """Test error handling for empty class name."""
        tools = LocalRepoTools(temp_repo)
        result = await tools.get_type_hierarchy("")
        assert "ERROR" in result

    @pytest.mark.asyncio
    async def test_nonexistent_class(self, temp_repo):
        """Test error handling for non-existent class."""
        tools = LocalRepoTools(temp_repo)
        result = await tools.get_type_hierarchy("NonExistentClass")
        assert "ERROR" in result or "not found" in result.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

