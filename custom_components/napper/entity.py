"""Base entity mixin for Napper entities."""

from __future__ import annotations

from homeassistant.helpers.entity import Entity


class NapperTimestampedEntity(Entity):
    """Base mixin for Napper entities (history & last_changed are synced via recorder_sync)."""
