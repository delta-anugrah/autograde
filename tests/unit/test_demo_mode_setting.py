"""DEMO_MODE: browser-only simulation for demo-autograde.smagri.id, never at a factory."""
import pytest

from palmgrade.core.config import Settings


def _settings(monkeypatch, **env):
    for k in ("DEMO_MODE", "PLC_ENABLED", "PLC_HOST", "SCALE_PLC_HOST", "SCALE_PLC_REGISTER"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return Settings()


def test_off_by_default(monkeypatch):
    assert _settings(monkeypatch).demo_mode is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes"])
def test_on_values(monkeypatch, value):
    assert _settings(monkeypatch, DEMO_MODE=value).demo_mode is True


@pytest.mark.parametrize("env", [
    {"PLC_ENABLED": "true"},
    {"PLC_HOST": "192.168.3.39"},
    {"SCALE_PLC_HOST": "192.168.3.39"},
    {"SCALE_PLC_REGISTER": "D100"},
])
def test_refuses_with_real_hardware(monkeypatch, env):
    s = _settings(monkeypatch, DEMO_MODE="1", **env)
    with pytest.raises(RuntimeError, match="DEMO_MODE"):
        s.validate_demo_mode()


def test_demo_without_hardware_boots(monkeypatch):
    _settings(monkeypatch, DEMO_MODE="1").validate_demo_mode()


def test_hardware_without_demo_boots(monkeypatch):
    _settings(monkeypatch, PLC_HOST="192.168.3.39").validate_demo_mode()
