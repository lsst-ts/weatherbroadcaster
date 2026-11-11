"""Tests for the weather data update command."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from weatherbroadcaster.config import config
from weatherbroadcaster.models import Data
from weatherbroadcaster.update_weather import main


@pytest.mark.asyncio
async def test_main_writes_weather_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Test that the update command writes weather data to the cache."""
    weather_data_file_path = tmp_path / "weather.json"

    async def fetch_weather_data() -> Data:
        return Data(
            TIME=datetime(2026, 5, 22, 12, 0, tzinfo=UTC),
            TEMPERATURE=8.2,
            RELATIVEHUMIDITY=41.5,
            WINDDIRECTION=275.0,
            WINDSPEED=4.3,
            DEWPOINT=1.2,
            PRECIPITATION=0.1,
        )

    monkeypatch.setattr(
        "weatherbroadcaster.update_weather.fetch_weather_data",
        fetch_weather_data,
    )
    monkeypatch.setattr(
        config,
        "weather_data_file_path",
        weather_data_file_path,
    )

    await main()

    assert weather_data_file_path.read_text() == (
        '{"STATIONID": "RUBINOBS01", "TIME": "2026-05-22T12:00:00Z", '
        '"LAT": -30.244633333, "LON": -70.7494166667, "HEIGHT": 2647.0, '
        '"TEMPERATURE": 8.2, "WINDSPEED": 4.3, "WINDDIRECTION": 275.0, '
        '"RELATIVEHUMIDITY": 41.5, "DEWPOINT": 1.2, '
        '"PRECIPITATION": 0.1}'
    )
    assert list(tmp_path.glob(".weather.json.*.tmp")) == []


@pytest.mark.asyncio
async def test_main_does_not_write_cache_after_timeout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Test a weather-fetch timeout leaves no cache file behind."""
    weather_data_file_path = tmp_path / "weather.json"
    weather_data_file_path.write_text("previous weather")

    async def fetch_weather_data() -> Data:
        raise TimeoutError

    monkeypatch.setattr(
        "weatherbroadcaster.update_weather.fetch_weather_data",
        fetch_weather_data,
    )
    monkeypatch.setattr(
        config, "weather_data_file_path", weather_data_file_path
    )

    with pytest.raises(TimeoutError):
        await main()

    assert weather_data_file_path.read_text() == "previous weather"
