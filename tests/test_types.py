"""Tests for types module (Citation, etc.)."""

import pytest
from cr.types import Citation


class TestCitationParse:
    """Tests for Citation.parse classmethod."""

    def test_range_parse(self):
        """Test parsing path:start-end range format."""
        citation = Citation.parse("src/main.py:10-20")
        assert citation is not None
        assert citation.path == "src/main.py"
        assert citation.start_line == 10
        assert citation.end_line == 20

    def test_single_line_parse(self):
        """Test parsing path:line format (single line)."""
        citation = Citation.parse("src/main.py:42")
        assert citation is not None
        assert citation.path == "src/main.py"
        assert citation.start_line == 42
        assert citation.end_line == 42

    def test_deep_path_parse(self):
        """Test parsing with deep nested path."""
        citation = Citation.parse("src/components/Button/index.tsx:5-15")
        assert citation is not None
        assert citation.path == "src/components/Button/index.tsx"
        assert citation.start_line == 5
        assert citation.end_line == 15

    def test_invalid_no_colon(self):
        """Test parse returns None when no colon present."""
        citation = Citation.parse("just/a/path.py")
        assert citation is None

    def test_invalid_non_numeric(self):
        """Test parse returns None when line numbers are non-numeric."""
        citation = Citation.parse("file.py:abc-def")
        assert citation is None

    def test_invalid_empty_range(self):
        """Test parse returns None when range is empty after colon."""
        citation = Citation.parse("file.py:")
        assert citation is None

    def test_invalid_partial_range(self):
        """Test parse returns None when only one side of range."""
        citation = Citation.parse("file.py:10-")
        assert citation is None


class TestCitationStr:
    """Tests for Citation.__str__ method."""

    def test_str_format(self):
        """Test string representation is path:start-end."""
        citation = Citation(path="src/main.py", start_line=10, end_line=20)
        assert str(citation) == "src/main.py:10-20"

    def test_str_single_line(self):
        """Test string representation with same start/end."""
        citation = Citation(path="src/main.py", start_line=42, end_line=42)
        assert str(citation) == "src/main.py:42-42"
