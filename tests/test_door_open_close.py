"""Tests for Door state machine open/close signal handling."""
from __future__ import annotations

import pytest

from custom_components.door_supervisor.models import DoorConfig


def test_door_config_requires_at_least_one_entity():
    with pytest.raises(ValueError):
        DoorConfig(name="Empty Door")


def test_door_config_thresholds_sorted_unique():
    cfg = DoorConfig(
        name="Front Door",
        sensor_entity_id="binary_sensor.front_door",
        left_open_thresholds_minutes=(90, 30, 60, 30),
    )
    assert cfg.left_open_thresholds_minutes == (30, 60, 90)


def test_has_open_close_signal_true_for_sensor_or_cover():
    assert DoorConfig(name="A", sensor_entity_id="binary_sensor.a").has_open_close_signal
    assert DoorConfig(name="B", cover_entity_id="cover.b").has_open_close_signal


def test_has_open_close_signal_false_for_lock_only():
    assert not DoorConfig(name="C", lock_entity_id="lock.c").has_open_close_signal
