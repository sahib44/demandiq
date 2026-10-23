"""Environment configuration shared by API and separate durable workers."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from backend.app.db.repository import postgres_url


@dataclass(frozen=True)
class Settings:
    database_url: str = ""
    data_dir: Path = field(default_factory=lambda: Path("data"))
    artifact_dir: Path = field(default_factory=lambda: Path("artifacts"))
    ledger_dir: Path | None = None
    max_attempts: int = 3
    lease_seconds: int = 60
    poll_seconds: float = 1.0
    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")
    max_request_bytes: int = 1_048_576
    api_root_path: str = ""

    def __post_init__(self):
        if self.database_url:
            postgres_url(self.database_url)
        if not isinstance(self.api_root_path, str) or (
            self.api_root_path
            and not re.fullmatch(
                r"/[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*", self.api_root_path
            )
        ):
            raise ValueError("Invalid API root path")
        for name in ("data_dir", "artifact_dir"):
            object.__setattr__(self, name, Path(getattr(self, name)).resolve())
        object.__setattr__(
            self,
            "ledger_dir",
            Path(self.ledger_dir or self.data_dir / "evaluation-ledger").resolve(),
        )
        for name, low, high in (
            ("max_attempts", 1, 5),
            ("lease_seconds", 3, 3600),
            ("max_request_bytes", 1024, 10_485_760),
        ):
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"Invalid {name}")
        if (
            isinstance(self.poll_seconds, bool)
            or not isinstance(self.poll_seconds, int | float)
            or not 0.01 <= self.poll_seconds <= 60
        ):
            raise ValueError("Invalid poll_seconds")
        if not isinstance(self.cors_origins, tuple) or any(
            not isinstance(v, str)
            or not v.startswith(("http://", "https://"))
            or "\n" in v
            for v in self.cors_origins
        ):
            raise ValueError("Invalid CORS origins")

    @classmethod
    def from_env(cls):
        try:
            return cls(
                database_url=os.getenv("DATABASE_URL", ""),
                data_dir=Path(os.getenv("DEMANDIQ_DATA_DIR", "data")),
                artifact_dir=Path(os.getenv("DEMANDIQ_ARTIFACT_DIR", "artifacts")),
                ledger_dir=(
                    Path(os.environ["DEMANDIQ_LEDGER_DIR"])
                    if os.getenv("DEMANDIQ_LEDGER_DIR")
                    else None
                ),
                max_attempts=int(os.getenv("JOB_MAX_ATTEMPTS", "3")),
                lease_seconds=int(os.getenv("JOB_LEASE_SECONDS", "60")),
                poll_seconds=float(os.getenv("JOB_POLL_SECONDS", "1")),
                max_request_bytes=int(os.getenv("MAX_REQUEST_BYTES", "1048576")),
                api_root_path=os.getenv("API_ROOT_PATH", ""),
                cors_origins=tuple(
                    v.strip()
                    for v in os.getenv(
                        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
                    ).split(",")
                    if v.strip()
                ),
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid backend environment configuration") from exc

    def ensure_directories(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.artifact_dir.mkdir(parents=True, exist_ok=True)

    def safe_config(self):
        return {
            "application": "DemandIQ",
            "api_version": "1.0.0",
            "job_max_attempts": self.max_attempts,
            "job_lease_seconds": self.lease_seconds,
            "forecast_horizon_weeks": 1,
            "inventory_scope": "retrospective_assumption_driven",
            "authentication": False,
        }
