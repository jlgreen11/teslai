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

    tesla_client_id: str = ""
    tesla_client_secret: str = ""
    tesla_region: str = "na"
    tesla_vin: str = ""

    teslai_session_secret: str = ""
