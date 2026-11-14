"""Android exhaustive defaults (0 = until exhausted) and Thorough soft-cap floors."""
from __future__ import annotations

import pytest

from backend.android import AndroidEnvironmentError, validate_mobile_config


def _base(**extra):
    cfg = {
        "app_mode": "installed",
        "package_name": "com.example.demo",
        "device_id": "emulator-5554",
        "max_screens": 0,
        "max_actions": 0,
        "max_depth": 0,
        "discovery_timeout_s": 0,
        "max_scroll_actions": 0,
        "max_scrolls_per_screen": 0,
        "max_candidates_per_screen": 0,
        "max_interactions": 0,
        "interaction_timeout_s": 0,
    }
    cfg.update(extra)
    return cfg


def test_default_is_exhaustive_until_done():
    got = validate_mobile_config(_base())
    assert got["thorough"] is False
    assert got["max_screens"] == 0
    assert got["max_actions"] == 0
    assert got["max_depth"] == 0
    assert got["max_interactions"] == 0
    assert got["discovery_timeout_s"] == 0


def test_thorough_raises_only_when_soft_caps_set():
    got = validate_mobile_config(_base(
        thorough=True, max_screens=40, max_actions=60, max_depth=5,
        discovery_timeout_s=600, max_scroll_actions=30, max_scrolls_per_screen=4,
        max_candidates_per_screen=12, max_interactions=300, interaction_timeout_s=2700,
    ))
    assert got["thorough"] is True
    assert got["max_screens"] == 80
    assert got["max_actions"] == 150
    assert got["max_depth"] == 8
    assert got["discovery_timeout_s"] == 900
    assert got["max_interactions"] == 500
    assert got["interaction_timeout_s"] == 3600


def test_thorough_keeps_zero_as_exhaustive():
    got = validate_mobile_config(_base(thorough=True))
    assert got["max_screens"] == 0
    assert got["max_actions"] == 0
    assert got["max_interactions"] == 0


def test_hard_caps_still_enforced():
    with pytest.raises(AndroidEnvironmentError, match="0-100 screens"):
        validate_mobile_config(_base(max_screens=101))
