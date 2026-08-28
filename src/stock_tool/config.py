"""Stable defaults introduced for the Sprint 1 release baseline."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FeatureFlags:
    """Declare safe defaults before later UI and service migrations.

    These flags intentionally have no runtime consumers in Sprint 1. They make
    the current product posture explicit: the legacy dashboard remains active
    and the future research workspace stays disabled until its own sprint.
    """

    legacy_dashboard_enabled: bool = True
    research_workspace_enabled: bool = False
    provider_contracts_enabled: bool = False


DEFAULT_FEATURE_FLAGS = FeatureFlags()
