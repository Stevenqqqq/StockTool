"""Corporate-history models used by point-in-time research imports."""

from __future__ import annotations

from enum import StrEnum


class MembershipStatus(StrEnum):
    """Known membership states; placeholders represent an explicit data gap."""

    LISTED = "listed"
    DELISTED = "delisted"
    DELISTED_PLACEHOLDER = "delisted_placeholder"


class DatasetCompleteness(StrEnum):
    """Completeness declared by the imported historical-universe source."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    UNKNOWN = "unknown"
