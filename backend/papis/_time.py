# backend/papis/_time.py
"""
Shared UTC-now helper.

datetime.utcnow() is deprecated (Python 3.12+) in favour of
datetime.now(timezone.utc) — but that returns a TIMEZONE-AWARE datetime,
which would silently change the stored format and comparison semantics
for every existing naive datetime already in the database. Every
created_at/occurred_at/updated_at column is declared as plain DateTime
(not DateTime(timezone=True)), and the production database already has
thousands of real rows stored as naive timestamps.

This helper produces the exact same VALUE and naive-ness that
datetime.utcnow() always did, using only non-deprecated APIs — a true
drop-in replacement with zero behavioural change for existing data.
"""
from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
