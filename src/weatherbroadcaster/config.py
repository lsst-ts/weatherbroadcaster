"""Configuration definition."""

from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from safir.logging import LogLevel, Profile

__all__ = ["Config", "config"]


class Config(BaseSettings):
    """Configuration for weatherbroadcaster."""

    model_config = SettingsConfigDict(
        env_prefix="WEATHERBROADCASTER_", case_sensitive=False
    )

    log_level: LogLevel = Field(
        LogLevel.INFO, title="Log level of the application's logger"
    )

    log_profile: Profile = Field(
        Profile.development, title="Application logging profile"
    )

    name: str = Field("weatherbroadcaster", title="Name of application")

    path_prefix: str = Field(
        "/weatherbroadcaster", title="URL prefix for application"
    )

    slack_webhook: SecretStr | None = Field(
        None,
        title="Slack webhook for alerts",
        description="If set, alerts will be posted to this Slack webhook",
    )
    weather_data_file_path: Path = Field(
        Path("/data/weather.json"),
        title="The path to write the weather.json file.",
    )
    efd_name: str = Field(
        "usdf_efd", min_length=1, title="Repertoire EFD database label"
    )
    efd_token_file_path: Path = Field(
        Path("/var/run/secrets/weatherbroadcaster/efd-token"),
        title="Path to a Gafaelfawr token with read:sasquatch scope",
    )
    weather_fetch_timeout: float = Field(
        30,
        gt=0,
        title=(
            "Maximum number of seconds to wait for weather data from the EFD."
        ),
    )
    weather_update_interval: int = Field(
        60 * 60,
        gt=0,
        title="Number of seconds between weather cache updates.",
    )


config = Config()
"""Configuration for weatherbroadcaster."""
