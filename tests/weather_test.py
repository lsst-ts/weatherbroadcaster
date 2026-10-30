"""Tests for weather data retrieval."""

import asyncio
import json
import os
from datetime import UTC, datetime
from math import nan
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar, Self, override

import pandas as pd
import pytest
from lsst_efd_client import EfdClient
from pydantic import HttpUrl, SecretStr
from rubin.repertoire import InfluxDatabaseWithCredentials

from weatherbroadcaster import weather
from weatherbroadcaster.config import config


def _efd_result(
    fields: dict[str, float | str | None | list[float | str | None]],
    index: list[datetime] | None = None,
) -> pd.DataFrame:
    """Create a fake EFD query result."""
    values = {
        field: value if isinstance(value, list) else [value]
        for field, value in fields.items()
    }
    if index is None:
        index = [
            datetime(2026, 5, 22, 11, 0, tzinfo=UTC),
            datetime(2026, 5, 22, 12, 0, tzinfo=UTC),
        ]
    return pd.DataFrame(values, index=index)


class _InfluxClient:
    closed = False

    def close(self) -> None:
        self.closed = True


class _EfdClient:
    expected_name: ClassVar[str] = "usdf_efd"
    queries: ClassVar[list[str]] = []
    influx_client = _InfluxClient()
    auth_path: ClassVar[Path]

    def __init__(self, *, efd_name: str, client: object) -> None:
        assert efd_name == self.expected_name
        assert client is not None
        type(self).auth_path = Path(os.environ["EFDAUTH"])
        assert self.auth_path.stat().st_mode & 0o777 == 0o600
        assert json.loads(self.auth_path.read_text())[self.expected_name] == {
            "url": "https://example.com/influxdb",
            "database": "efd",
            "schema_registry": "https://example.com/registry",
            "username": "reader",
            "password": "password",
        }
        self._influx_client = self.influx_client

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        self._influx_client.close()

    async def influxql_query(self, query: str) -> pd.DataFrame:
        assert "salIndex=301" in query
        self.queries.append(query)

        if "lsst.sal.ESS.temperature" in query:
            return _efd_result({"mean_temperature": [7.1, 8.2]})
        if "lsst.sal.ESS.relativeHumidity" in query:
            return _efd_result({"mean_relative_humidity": [40.0, 41.5]})
        if "lsst.sal.ESS.airFlow" in query:
            return _efd_result(
                {
                    "direction": [270.0, 280.0],
                    "speed": [3.1, 4.3],
                }
            )
        if "lsst.sal.ESS.dewPoint" in query:
            return _efd_result({"mean_dew_point": [0.5, 1.2]})
        if "lsst.sal.ESS.rainRate" in query:
            return _efd_result({"mean_rain_rate": [0.0, 0.1]})

        raise AssertionError(f"Unexpected query: {query}")


class _HangingEfdClient(_EfdClient):
    influx_client = _InfluxClient()

    @override
    async def influxql_query(self, query: str) -> pd.DataFrame:
        await asyncio.Event().wait()


class _DiscoveryClient:
    def __init__(self) -> None:
        self.info: InfluxDatabaseWithCredentials | None = (
            InfluxDatabaseWithCredentials(
                url=HttpUrl("https://example.com/influxdb"),
                database="efd",
                schema_registry=HttpUrl("https://example.com/registry"),
                username="reader",
                password=SecretStr("password"),
            )
        )
        self.closed = False
        self.requested: tuple[str, str] | None = None
        self.error: Exception | None = None
        self.stall = False

    async def influxdb_credentials(
        self, database: str, token: str
    ) -> InfluxDatabaseWithCredentials | None:
        self.requested = (database, token)
        if self.stall:
            await asyncio.Event().wait()
        if self.error:
            raise self.error
        return self.info

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture
def discovery(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> _DiscoveryClient:
    token_path = tmp_path / "token"
    token_path.write_text("secret-token\n")
    monkeypatch.setattr(config, "efd_token_file_path", token_path)
    client = _DiscoveryClient()
    monkeypatch.setattr(weather, "DiscoveryClient", lambda: client)
    return client


@pytest.mark.asyncio
@pytest.mark.parametrize("efd_name", ["usdf_efd", "usdfdev_efd"])
async def test_fetch_weather_data(
    monkeypatch: pytest.MonkeyPatch,
    discovery: _DiscoveryClient,
    efd_name: str,
) -> None:
    """Test fetching weather data from the EFD."""
    _EfdClient.queries = []
    _EfdClient.influx_client = _InfluxClient()
    monkeypatch.setattr(weather, "EfdClient", _EfdClient)
    monkeypatch.setattr(config, "efd_name", efd_name)
    monkeypatch.setattr(_EfdClient, "expected_name", efd_name)
    monkeypatch.setenv("EFDAUTH", "previous-auth-file")

    data = await weather.fetch_weather_data()

    assert len(_EfdClient.queries) == 5
    assert any("mean_temperature" in query for query in _EfdClient.queries)
    assert any(
        "mean_relative_humidity" in query for query in _EfdClient.queries
    )
    assert any("direction, speed" in query for query in _EfdClient.queries)
    assert any("mean_dew_point" in query for query in _EfdClient.queries)
    assert any("mean_rain_rate" in query for query in _EfdClient.queries)

    assert datetime(2026, 5, 22, 12, 0, tzinfo=UTC) == data.TIME
    assert data.TEMPERATURE == 8.2
    assert data.RELATIVEHUMIDITY == 41.5
    assert pytest.approx(275.813, abs=0.001) == data.WINDDIRECTION
    assert data.WINDSPEED == 3.7
    assert data.DEWPOINT == 1.2
    assert data.PRECIPITATION == 0.1
    assert data.LAT == -30.244633333
    assert data.LON == -70.7494166667
    assert data.HEIGHT == 2647
    assert _EfdClient.influx_client.closed
    assert discovery.requested == (efd_name, "secret-token")
    assert discovery.closed
    assert not _EfdClient.auth_path.exists()
    assert os.environ["EFDAUTH"] == "previous-auth-file"


@pytest.mark.asyncio
async def test_fetch_weather_data_times_out_and_closes_client(
    monkeypatch: pytest.MonkeyPatch,
    discovery: _DiscoveryClient,
) -> None:
    """Test a stalled EFD query times out and closes its client."""
    _HangingEfdClient.influx_client = _InfluxClient()
    monkeypatch.setattr(weather, "EfdClient", _HangingEfdClient)
    monkeypatch.setattr(config, "weather_fetch_timeout", 0.01)

    with pytest.raises(TimeoutError):
        await weather.fetch_weather_data()

    assert _HangingEfdClient.influx_client.closed
    assert discovery.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("efd_name", ["usdf_efd", "usdfdev_efd"])
async def test_fetch_weather_data_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
    discovery: _DiscoveryClient,
    efd_name: str,
) -> None:
    """Fail closed when Repertoire does not know the EFD database."""
    discovery.info = None
    monkeypatch.setattr(weather, "EfdClient", _EfdClient)
    monkeypatch.setattr(config, "efd_name", efd_name)

    with pytest.raises(RuntimeError, match=f"no {efd_name}"):
        await weather.fetch_weather_data()

    assert discovery.closed


@pytest.mark.asyncio
async def test_fetch_weather_data_without_token(
    discovery: _DiscoveryClient,
) -> None:
    """Do not contact Repertoire when the token file is empty."""
    config.efd_token_file_path.write_text("")

    with pytest.raises(RuntimeError, match="token file is empty"):
        await weather.fetch_weather_data()

    assert discovery.requested is None


@pytest.mark.asyncio
async def test_fetch_weather_data_discovery_error(
    discovery: _DiscoveryClient,
) -> None:
    """Close Repertoire after a failed credential request."""
    discovery.error = RuntimeError("Repertoire unavailable")

    with pytest.raises(RuntimeError, match="Repertoire unavailable"):
        await weather.fetch_weather_data()

    assert discovery.closed


@pytest.mark.asyncio
async def test_fetch_weather_data_discovery_timeout(
    monkeypatch: pytest.MonkeyPatch, discovery: _DiscoveryClient
) -> None:
    """Apply the weather timeout to credential discovery."""
    discovery.stall = True
    monkeypatch.setattr(config, "weather_fetch_timeout", 0.01)

    with pytest.raises(TimeoutError):
        await weather.fetch_weather_data()

    assert discovery.closed


@pytest.mark.asyncio
async def test_real_efd_client_uses_efdauth(
    monkeypatch: pytest.MonkeyPatch, discovery: _DiscoveryClient
) -> None:
    """The installed EFD client must not request Segwarides credentials."""
    requested_urls: list[str] = []

    def get(url: str) -> SimpleNamespace:
        requested_urls.append(url)
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr("lsst_efd_client.efd_helper.requests.get", get)
    assert discovery.info is not None
    async with weather._create_efd_client(discovery.info) as client:
        assert isinstance(client, EfdClient)

    assert requested_urls == []
    assert (
        client._influx_client.url
        == "https://example.com:443/influxdb/{endpoint}"
    )
    assert client._influx_client.db == "efd"
    assert (
        client._influx_client.opts["raise_for_status"]
        is weather._check_influx_response
    )


def test_read_mean_missing_column() -> None:
    """Test missing EFD result columns are reported clearly."""
    result = _efd_result({})
    result.index = [datetime(2026, 5, 22, 12, 0, tzinfo=UTC)]

    with pytest.raises(RuntimeError, match="mean_relative_humidity"):
        weather._read_mean(
            result, "mean_relative_humidity", "relativeHumidity"
        )


def test_read_mean_empty_result() -> None:
    """Test empty EFD query results return the missing-value marker."""
    result = pd.DataFrame({"mean_relative_humidity": []})

    assert (
        weather._read_mean(
            result, "mean_relative_humidity", "relativeHumidity"
        )
        == -999
    )


@pytest.mark.parametrize("value", [None, nan, "null"])
def test_read_mean_null_value(value: float | str | None) -> None:
    """Test null non-rain values return the missing-value marker."""
    result = _efd_result({"mean_temperature": value})

    assert (
        weather._read_mean(result, "mean_temperature", "temperature") == -999
    )


@pytest.mark.parametrize("value", [None, nan, "null"])
def test_read_mean_null_rain_rate(value: float | str | None) -> None:
    """Test null rain-rate values are returned as zero."""
    result = _efd_result({"mean_rain_rate": value})

    assert weather._read_mean(result, "mean_rain_rate", "rainRate") == 0


def test_read_mean_uses_latest_bucket() -> None:
    """Test grouped query results use the newest bucket."""
    result = _efd_result({"mean_temperature": [7.1, 8.2]})

    assert weather._read_mean(result, "mean_temperature", "temperature") == 8.2


def test_calculate_wind_direction_weights_by_speed() -> None:
    """Test stronger winds contribute more to average direction."""
    result = _efd_result(
        {
            "direction": [0.0, 90.0],
            "speed": [1.0, 3.0],
        }
    )

    assert pytest.approx(71.565, abs=0.001) == (
        weather._calculate_wind_direction(result)
    )


def test_calculate_wind_direction_zero_speed() -> None:
    """Test wind direction is missing when all speed weights are zero."""
    result = _efd_result(
        {
            "direction": [0.0, 90.0],
            "speed": [0.0, 0.0],
        }
    )

    assert weather._calculate_wind_direction(result) == -999


def test_latest_timestamp_uses_latest_non_empty_result() -> None:
    """Test timestamp selection uses the latest available query result."""
    older = _efd_result(
        {"mean_temperature": 8.2},
        index=[datetime(2026, 5, 22, 12, 0, tzinfo=UTC)],
    )
    newer = _efd_result(
        {"mean_relative_humidity": 41.5},
        index=[datetime(2026, 5, 22, 13, 0, tzinfo=UTC)],
    )
    empty = _efd_result({"mean_dew_point": 1.2}, index=[])

    assert datetime(2026, 5, 22, 13, 0, tzinfo=UTC) == (
        weather._latest_timestamp(older, newer, empty)
    )
