"""Tests for application configuration."""

import pytest
from pydantic import ValidationError

from weatherbroadcaster.config import Config


def test_efd_name_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Read the discovery label from the environment."""
    monkeypatch.delenv("WEATHERBROADCASTER_EFD_NAME", raising=False)
    assert Config().efd_name == "usdf_efd"
    monkeypatch.setenv("WEATHERBROADCASTER_EFD_NAME", "usdfdev_efd")
    assert Config().efd_name == "usdfdev_efd"
    monkeypatch.setenv("WEATHERBROADCASTER_EFD_NAME", "")
    with pytest.raises(ValidationError):
        Config()


@pytest.mark.parametrize(
    "setting", ["weather_fetch_timeout", "weather_update_interval"]
)
def test_weather_timing_settings_must_be_positive(setting: str) -> None:
    """Reject non-positive weather timing settings."""
    with pytest.raises(ValidationError):
        Config.model_validate({setting: 0})
