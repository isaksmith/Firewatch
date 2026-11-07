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
    poll_minutes: int | None = None  # legacy: if set, overrides the FIRMS interval only (minutes)
    # Per-source poll intervals in seconds, about as fast as each source really updates.
    poll_firms_s: int = 60
    poll_nws_s: int = 60
    poll_lsr_s: int = 300
    poll_wfigs_incidents_s: int = 300
    poll_wfigs_perimeters_s: int = 900
    poll_metar_s: int = 300
    poll_open_meteo_s: int = 3600
    poll_spc_s: int = 1800
    poll_hms_s: int = 1800
    poll_goes_fire_s: int = 60
    poll_goes_lightning_s: int = 60
    poll_goes_smoke_s: int = 300
    poll_rtma_ru_s: int = 900
    poll_landsat_nrt_s: int = 300  # only polled when a FIRMS key is set
    firms_sources: str = "VIIRS_SNPP_NRT,VIIRS_NOAA20_NRT,VIIRS_NOAA21_NRT,MODIS_NRT"
    scorer: str = "auto"  # auto (model if present, else rules) | model | rules
    threshold_escalate: int = 70
    threshold_investigate: int = 40
    curing_pct_override: float | None = None
    # Gust threshold for the lines-under-wind flag. An assumed value, not a utility standard.
    wind_gust_flag_kmh: float = 80.0
    nws_user_agent: str = "firewatch-hackathon"
    db_path: str = str(DATA_DIR / "firewatch.sqlite")
    district: str = "cottonwood-creek"  # data/districts/<slug>/
    sms_gateway: str = "outbox"  # outbox (records only) | twilio
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from: str = ""
    public_base_url: str = ""  # used to verify Twilio webhook signatures
    mesh_gateway: str = "off"  # off | serial | tcp: a Meshtastic radio attached to the server
    mesh_device: str = ""  # serial port (first Meshtastic port when blank) or the radio's host for tcp
    mesh_channel_index: int = 0
    scenario_seconds_per_minute: float = 2.0
    api_token: str = ""  # when set, required (X-Firewatch-Token) on endpoints that can text people
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def bbox_tuple(self) -> tuple[float, float, float, float]:
        w, s, e, n = (float(x) for x in self.bbox.split(","))
        return w, s, e, n

    @property
    def source_intervals(self) -> dict[str, int]:
        """Poll interval in seconds per source name (the names used in source_health)."""
        firms = self.poll_minutes * 60 if self.poll_minutes else self.poll_firms_s
        return {
            "firms": firms,
            "nws_alerts": self.poll_nws_s,
            "lsr": self.poll_lsr_s,
            "wfigs_incidents": self.poll_wfigs_incidents_s,
            "wfigs_perimeters": self.poll_wfigs_perimeters_s,
            "metar": self.poll_metar_s,
            "open_meteo": self.poll_open_meteo_s,
            "spc": self.poll_spc_s,
            "hms": self.poll_hms_s,
            "goes_fire": self.poll_goes_fire_s,
            "goes_lightning": self.poll_goes_lightning_s,
            "goes_smoke": self.poll_goes_smoke_s,
            "rtma_ru": self.poll_rtma_ru_s,
            "landsat_nrt": self.poll_landsat_nrt_s,
        }

    @property
    def firms_source_list(self) -> list[str]:
        return [s.strip() for s in self.firms_sources.split(",") if s.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
