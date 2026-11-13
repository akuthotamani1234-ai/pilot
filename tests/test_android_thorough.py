"""Android Thorough raises discovery/user-like budgets within hard caps."""
from __future__ import annotations

import pytest

from backend.android import AndroidEnvironmentError, validate_mobile_config


def _base(**extra):
    cfg = {
        "app_mode": "installed",
        "package_name": "com.example.demo",
        "device_id": "emulator-5554",
        "max_screens": 40,
        "max_actions": 60,
        "max_depth": 5,
        "discovery_timeout_s": 600,
        "max_scroll_actions": 30,
        "max_scrolls_per_screen": 4,
        "max_candidates_per_screen": 12,
        "max_interactions": 300,
        "interaction_timeout_s": 2700,
    }
    cfg.update(extra)
    return cfg


def test_thorough_raises_android_budgets_within_caps():
    got = validate_mobile_config(_base(thorough=True))
    assert got["thorough"] is True
    assert got["max_screens"] == 80
    assert got["max_actions"] == 150
    assert got["max_depth"] == 8
    assert got["discovery_timeout_s"] == 900
    assert got["max_scroll_actions"] == 60
    assert got["max_scrolls_per_screen"] == 8
    assert got["max_candidates_per_screen"] == 24
    assert got["max_interactions"] == 500
    assert got["interaction_timeout_s"] == 3600


def test_thorough_does_not_lower_higher_manual_budgets():
    got = validate_mobile_config(_base(
        thorough=True, max_screens=95, max_actions=180, max_depth=9, max_interactions=500,
    ))
    assert got["max_screens"] == 95
    assert got["max_actions"] == 180
    assert got["max_depth"] == 9


def test_standard_keeps_defaults():
    got = validate_mobile_config(_base())
    assert got.get("thorough") is False
    assert got["max_screens"] == 40
    assert got["max_actions"] == 60
    assert got["max_interactions"] == 300


def test_thorough_still_respects_hard_caps():
    with pytest.raises(AndroidEnvironmentError, match="1-100 screens"):
        validate_mobile_config(_base(thorough=True, max_screens=101))
