"""Tests for output formatting module."""

import json
import pytest

from cli.output_formatter import (
    format_text,
    format_markdown,
    format_json,
    format_output,
)


class TestFormatText:
    """Tests for format_text function."""

    def test_basic_output(self):
        """Test plain text output with sources."""
        result = format_text(
            answer="Great PR!",
            sources=["src/main.py", "src/utils.py"],
            model="gemini/gemini-3-pro-preview",
        )
        assert "Great PR!" in result
        assert "Sources:" in result
        assert u"  • src/main.py" in result
        assert u"  • src/utils.py" in result
        assert u"— AsyncReview • gemini/gemini-3-pro-preview" in result

    def test_no_sources(self):
        """Test plain text output without sources."""
        result = format_text(
            answer="Looks good.",
            sources=[],
            model="gemini/gemini-3-pro-preview",
        )
        assert "Looks good." in result
        assert "Sources:" not in result
        assert u"— AsyncReview" in result

    def test_empty_answer(self):
        """Test plain text output with empty answer string."""
        result = format_text(
            answer="",
            sources=["src/main.py"],
            model="gemini/gemini-3-pro-preview",
        )
        assert "Sources:" in result
        assert u"  • src/main.py" in result
        assert u"— AsyncReview" in result
        lines = result.split("\n")
        assert lines[0] == ""

    def test_long_source_list(self):
        """Test plain text output with 200 sources."""
        sources = [f"src/file_{i}.py" for i in range(200)]
        result = format_text(
            answer="Lots of files!",
            sources=sources,
            model="gemini/gemini-3-pro-preview",
        )
        assert "Lots of files!" in result
        assert u"  • src/file_0.py" in result
        assert u"  • src/file_199.py" in result
        assert u"— AsyncReview" in result
        lines = result.split("\n")
        source_lines = [l for l in lines if l.startswith("  •")]
        assert len(source_lines) == 200

    def test_special_chars_in_sources(self):
        """Test plain text with special characters in source paths."""
        sources = [
            "src/émoji_🔍.py",
            "src/file with spaces.py",
            "src/<script>.py",
            "src/Unicode_üñíçödé.py",
            'src/file_with_"quotes".py',
            "src/back\\slashes.py",
        ]
        result = format_text(
            answer="Special chars test.",
            sources=sources,
            model="gemini/gemini-3-pro-preview",
        )
        assert "Special chars test." in result
        assert u"— AsyncReview" in result
        for source in sources:
            assert f"  • {source}" in result


class TestFormatMarkdown:
    """Tests for format_markdown function."""

    def test_markdown_output(self):
        """Test markdown output with sources."""
        result = format_markdown(
            answer="## Review",
            sources=["src/main.py"],
            model="gemini/gemini-3-pro-preview",
        )
        assert "## Review" in result
        assert "### Sources" in result
        assert "src/main.py" in result
        assert "---" in result
        assert "AsyncReview" in result

    def test_empty_answer(self):
        """Test markdown output with empty answer string."""
        result = format_markdown(
            answer="",
            sources=["src/main.py"],
            model="gemini/gemini-3-pro-preview",
        )
        assert "### Sources" in result
        assert "src/main.py" in result
        assert "---" in result
        lines = result.split("\n")
        assert lines[0] == ""

    def test_long_source_list(self):
        """Test markdown output with 200 sources."""
        sources = [f"src/file_{i}.py" for i in range(200)]
        result = format_markdown(
            answer="## Many files",
            sources=sources,
            model="gemini/gemini-3-pro-preview",
        )
        assert "## Many files" in result
        assert "### Sources" in result
        assert "- `src/file_0.py`" in result
        assert "- `src/file_199.py`" in result
        assert "---" in result
        assert "AsyncReview" in result
        # Verify count of source lines
        lines = result.split("\n")
        source_lines = [l for l in lines if l.startswith("- `")]
        assert len(source_lines) == 200

    def test_special_chars_in_sources(self):
        """Test markdown with special characters in source paths."""
        sources = [
            "src/émoji_🔍.py",
            "src/file with spaces.py",
            "src/<script>.py",
            "src/Unicode_üñíçödé.py",
            'src/file_with_"quotes".py',
            "src/back\\slashes.py",
        ]
        result = format_markdown(
            answer="## Special chars",
            sources=sources,
            model="gemini/gemini-3-pro-preview",
        )
        assert "## Special chars" in result
        assert "### Sources" in result
        assert "---" in result
        for source in sources:
            assert f"- `{source}`" in result


class TestFormatJson:
    """Tests for format_json function."""

    def test_json_basic(self):
        """Test JSON output without metadata."""
        result = format_json(
            answer="LGTM",
            sources=["src/main.py"],
            model="gemini/gemini-3-pro-preview",
        )
        data = json.loads(result)
        assert data["answer"] == "LGTM"
        assert data["sources"] == ["src/main.py"]
        assert data["model"] == "gemini/gemini-3-pro-preview"
        assert "metadata" not in data

    def test_json_with_metadata(self):
        """Test JSON output with metadata."""
        result = format_json(
            answer="LGTM",
            sources=["src/main.py"],
            model="gemini/gemini-3-pro-preview",
            metadata={"duration": 1.5, "files_reviewed": 1},
        )
        data = json.loads(result)
        assert data["answer"] == "LGTM"
        assert data["metadata"]["duration"] == 1.5
        assert data["metadata"]["files_reviewed"] == 1

    def test_empty_answer(self):
        """Test JSON output with empty answer string."""
        result = format_json(
            answer="",
            sources=["src/main.py"],
            model="gemini/gemini-3-pro-preview",
        )
        data = json.loads(result)
        assert data["answer"] == ""
        assert data["sources"] == ["src/main.py"]
        assert data["model"] == "gemini/gemini-3-pro-preview"

    def test_long_source_list(self):
        """Test JSON output with 200 sources."""
        sources = [f"src/file_{i}.py" for i in range(200)]
        result = format_json(
            answer="Many files",
            sources=sources,
            model="gemini/gemini-3-pro-preview",
        )
        data = json.loads(result)
        assert data["answer"] == "Many files"
        assert len(data["sources"]) == 200
        assert data["sources"][0] == "src/file_0.py"
        assert data["sources"][199] == "src/file_199.py"

    def test_special_chars_in_sources(self):
        """Test JSON output with special characters in source names."""
        sources = [
            "src/\u00e9moji_\U0001f50d.py",
            "src/file with spaces.py",
            "src/<script>.py",
            'src/file_with_"quotes".py',
        ]
        result = format_json(
            answer="Special chars",
            sources=sources,
            model="gemini/gemini-3-pro-preview",
        )
        data = json.loads(result)
        assert data["answer"] == "Special chars"
        assert data["sources"] == sources

    def test_json_with_metadata_empty_answer(self):
        """Test JSON with metadata and empty answer."""
        result = format_json(
            answer="",
            sources=[],
            model="gemini/gemini-3-pro-preview",
            metadata={"key": "value"},
        )
        data = json.loads(result)
        assert data["answer"] == ""
        assert data["sources"] == []
        assert data["metadata"]["key"] == "value"


class TestFormatOutput:
    """Tests for format_output dispatcher function."""

    def test_text_format(self):
        """Test format_output with text format."""
        result = format_output(
            answer="Hello",
            sources=[],
            model="m",
            output_format="text",
        )
        assert "Hello" in result
        assert u"— AsyncReview" in result

    def test_markdown_format(self):
        """Test format_output with markdown format."""
        result = format_output(
            answer="Hello",
            sources=[],
            model="m",
            output_format="markdown",
        )
        assert "Hello" in result
        assert "---" in result

    def test_json_format(self):
        """Test format_output with json format."""
        result = format_output(
            answer="Hello",
            sources=[],
            model="m",
            output_format="json",
        )
        data = json.loads(result)
        assert data["answer"] == "Hello"

    def test_default_format(self):
        """Test format_output defaults to text."""
        result = format_output(
            answer="Hello",
            sources=[],
            model="m",
        )
        assert "Hello" in result
        assert u"— AsyncReview" in result

    def test_empty_answer_all_formats(self):
        """Test format_output with empty answer across all formats."""
        for fmt in ["text", "markdown", "json"]:
            result = format_output(
                answer="",
                sources=["src/main.py"],
                model="gemini/gemini-3-pro-preview",
                output_format=fmt,
            )
            assert result is not None
            assert len(result) > 0

    def test_long_source_list_all_formats(self):
        """Test format_output with 200 sources across all formats."""
        sources = [f"src/file_{i}.py" for i in range(200)]
        for fmt in ["text", "markdown", "json"]:
            result = format_output(
                answer="Many files",
                sources=sources,
                model="gemini/gemini-3-pro-preview",
                output_format=fmt,
            )
            assert result is not None
            assert len(result) > 0

    def test_special_chars_all_formats(self):
        """Test format_output with special chars in sources across all formats."""
        sources = [
            "src/\u00e9moji_\U0001f50d.py",
            "src/file with spaces.py",
        ]
        for fmt in ["text", "markdown", "json"]:
            result = format_output(
                answer="Special chars",
                sources=sources,
                model="gemini/gemini-3-pro-preview",
                output_format=fmt,
            )
            assert result is not None
            assert len(result) > 0
            if fmt == "json":
                import json as _json
                data = _json.loads(result)
                assert data["sources"] == sources
            else:
                for source in sources:
                    assert source in result
