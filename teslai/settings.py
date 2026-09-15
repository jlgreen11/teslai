from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings, read from environment variables and `.env`."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    teslai_domain: str = ""
    teslai_telemetry_host: str = ""
    teslai_telemetry_port: int = 4443
    teslai_secrets_dir: Path = Path("./secrets")
    teslai_timezone: str = "UTC"

    database_url: str = ""
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_topic_base: str = "telemetry"
    teslai_recordings_dir: Path | None = Path("./recordings")

    tesla_client_id: str = ""
    tesla_client_secret: str = ""
    tesla_region: str = "na"
    tesla_vin: str = ""
    tesla_redirect_uri: str = ""
    tesla_proxy_url: str = "https://localhost:4443"
    tesla_proxy_ca: Path | None = None
    tesla_telemetry_exp_days: int = 365

    teslai_session_secret: str = ""
    teslai_notify_urls: str = ""
    teslai_backup_dir: Path | None = None
    teslai_homeassistant: bool = False
    teslai_pack_kwh: float = 75.0
