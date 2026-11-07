from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR / "data"
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_DIR / ".env", BACKEND_DIR / ".env"),
        extra="ignore",
    )

    firms_map_key: str = ""
    mode: str = "sample"  # sample | live
    bbox: str = "-102.05,36.99,-94.59,40.00"
    poll_minutes: int = 5
    firms_sources: str = "VIIRS_SNPP_NRT,VIIRS_NOAA20_NRT,VIIRS_NOAA21_NRT,MODIS_NRT"
    scorer: str = "auto"  # auto (model if present, else rules) | model | rules
    threshold_escalate: int = 70
    threshold_investigate: int = 40
    curing_pct_override: float | None = None
    nws_user_agent: str = "firewatch-demo (contact@example.com)"
    db_path: str = str(DATA_DIR / "firewatch.sqlite")
    district: str = "cottonwood-creek"  # data/districts/<slug>/
    sms_gateway: str = "outbox"  # outbox (records only) | twilio
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from: str = ""
    public_base_url: str = ""  # used to verify Twilio webhook signatures
    scenario_seconds_per_minute: float = 2.0
    api_token: str = ""  # when set, required (X-Firewatch-Token) on endpoints that can text people
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def bbox_tuple(self) -> tuple[float, float, float, float]:
        w, s, e, n = (float(x) for x in self.bbox.split(","))
        return w, s, e, n

    @property
    def firms_source_list(self) -> list[str]:
        return [s.strip() for s in self.firms_sources.split(",") if s.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
