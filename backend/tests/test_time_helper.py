# backend/tests/test_time_helper.py
"""
Tests for the utcnow() helper — verifies it's a true drop-in replacement
for the deprecated datetime.utcnow(): same value, same naive-ness.
"""
from datetime import datetime, timezone

from papis._time import utcnow


class TestUtcNow:

    def test_returns_naive_datetime(self):
        """Must stay naive — existing DB columns are plain DateTime, not
        DateTime(timezone=True), and thousands of existing rows are
        already stored as naive timestamps."""
        result = utcnow()
        assert result.tzinfo is None

    def test_value_matches_real_utc_time_closely(self):
        before = datetime.now(timezone.utc).replace(tzinfo=None)
        result = utcnow()
        after = datetime.now(timezone.utc).replace(tzinfo=None)
        assert before <= result <= after

    def test_not_accidentally_local_time(self):
        """A common mistake this helper must avoid: datetime.now() without
        UTC would return LOCAL time, silently corrupting every timestamp
        for anyone not in UTC+0."""
        utc_now = datetime.now(timezone.utc).replace(tzinfo=None)
        result = utcnow()
        # Should agree with true UTC to within a second, not off by a
        # timezone-offset's worth of hours.
        assert abs((result - utc_now).total_seconds()) < 1
