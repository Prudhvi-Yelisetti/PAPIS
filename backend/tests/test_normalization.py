# backend/tests/test_normalization.py
"""
Tests for the pure string-manipulation helpers: _strip_version and
_normalize_name. These underpin every matching decision the scanner
makes, so they get dedicated coverage before anything higher-level.
"""
import pytest

from papis.scanner import _strip_version, _normalize_name


class TestStripVersion:

    @pytest.mark.parametrize("raw,expected", [
        ("requests", "requests"),
        ("requests>=2.28.0", "requests"),
        ("requests==2.28.0", "requests"),
        ("requests<3.0", "requests"),
        ("requests!=2.0.0", "requests"),
        ("requests[security]>=2.28.0", "requests"),
        ("requests ; python_version >= '3.8'", "requests"),
        ("  requests  ", "requests"),
        ("fastapi[all]", "fastapi"),
    ])
    def test_strips_version_specifiers(self, raw, expected):
        assert _strip_version(raw) == expected


class TestNormalizeName:

    @pytest.mark.parametrize("raw,expected", [
        ("requests", "requests"),
        ("Requests", "requests"),
        ("types-requests", "types-requests"),
        ("types_requests", "types-requests"),
        ("Types.Requests", "types-requests"),
        ("types__requests", "types-requests"),   # collapses repeated separators
        ("  requests  ", "requests"),
        ("python-dotenv", "python-dotenv"),
        ("python_dotenv", "python-dotenv"),
    ])
    def test_pep503_style_normalization(self, raw, expected):
        assert _normalize_name(raw) == expected

    def test_different_separator_styles_collapse_to_same_key(self):
        """The whole point of normalization: these must all match."""
        variants = ["types-requests", "types_requests", "Types.Requests", "TYPES-REQUESTS"]
        normalized = {_normalize_name(v) for v in variants}
        assert len(normalized) == 1
