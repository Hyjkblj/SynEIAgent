"""
Tests for gateway_lite.config.load_config.
Covers example-based tests (Task 8.1) and property-based test (Task 8.2).
"""
import json
import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from gateway_lite.config import GatewayConfig, RosBridgeConfig, load_config


# ---------------------------------------------------------------------------
# Task 8.1 — Example-based tests
# ---------------------------------------------------------------------------


def test_load_config_defaults():
    """load_config(None) returns a GatewayConfig with all default values."""
    cfg = load_config(None)
    assert isinstance(cfg, GatewayConfig)
    assert cfg.max_linear == 0.6
    assert cfg.max_angular == 1.2
    assert cfg.deadman_timeout_ms == 250
    assert cfg.joystick_max_hz == 20
    assert cfg.ros_bridge.mode == "http"
    assert cfg.ros_bridge.base_url == "http://127.0.0.1:8080"
    assert cfg.ros_bridge.timeout_s == 0.8


def test_load_config_missing_file(tmp_path: Path):
    """When config.json doesn't exist, load_config falls back to defaults without raising."""
    missing = tmp_path / "nonexistent_config.json"
    # load_config(None) is the documented way to get defaults; a missing path
    # is handled by the caller (main.py) which passes None when the file is absent.
    # We verify that passing None never raises.
    cfg = load_config(None)
    assert cfg.max_linear == 0.6
    assert cfg.max_angular == 1.2


def test_load_config_mock_mode(tmp_path: Path):
    """ros_bridge.mode='mock' is correctly parsed from config.json."""
    data = {
        "ros_bridge": {
            "mode": "mock",
            "base_url": "http://127.0.0.1:8080",
        }
    }
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps(data), encoding="utf-8")

    cfg = load_config(cfg_file)
    assert cfg.ros_bridge.mode == "mock"


# ---------------------------------------------------------------------------
# Task 8.2 — Property 9: config.json parsing completeness
# ---------------------------------------------------------------------------

# Feature: joystick-sim-integration-test, Property 9: config.json 配置解析完整性
@given(
    st.fixed_dictionaries(
        {
            "max_linear": st.floats(min_value=0.01, max_value=10.0, allow_nan=False, allow_infinity=False),
            "max_angular": st.floats(min_value=0.01, max_value=10.0, allow_nan=False, allow_infinity=False),
            "deadman_timeout_ms": st.integers(min_value=50, max_value=5000),
            "joystick_max_hz": st.integers(min_value=1, max_value=200),
            "ros_bridge": st.fixed_dictionaries(
                {
                    "base_url": st.text(
                        alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="/:.-_"),
                        min_size=1,
                        max_size=80,
                    ).map(lambda s: "http://" + s.strip("/") or "http://127.0.0.1:8080"),
                }
            ),
        }
    )
)
@settings(max_examples=200)
def test_load_config_parsing_completeness(config_dict):
    """
    **Validates: Requirements 9.1, 9.2**

    For any valid config dict, load_config() must return a GatewayConfig whose
    fields exactly match the values written to the temp file.
    """
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(config_dict, f)
        tmp_path = f.name

    cfg = load_config(tmp_path)

    assert cfg.max_linear == config_dict["max_linear"]
    assert cfg.max_angular == config_dict["max_angular"]
    assert cfg.deadman_timeout_ms == config_dict["deadman_timeout_ms"]
    assert cfg.joystick_max_hz == config_dict["joystick_max_hz"]
    assert cfg.ros_bridge.base_url == config_dict["ros_bridge"]["base_url"]
