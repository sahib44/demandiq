"""Strict, side-effect-free validation for asynchronous application requests."""

from __future__ import annotations

import math
from pathlib import PurePosixPath
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.app.services.configuration import phase3_config
from ml.inventory.config import ScenarioConfig

Digest = Annotated[str, Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")]
Identifier = Digest


def _finite_json(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Configuration must contain finite JSON numbers")
    if isinstance(value, dict):
        for item in value.values():
            _finite_json(item)
    elif isinstance(value, list):
        for item in value:
            _finite_json(item)


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class DatasetImportRequest(StrictRequest):
    source: Literal["existing", "official", "file"] = "existing"
    dataset_id: Digest | None = None
    input_file: Annotated[str, Field(min_length=1, max_length=512)] | None = None
    expected_sha256: Digest | None = None

    @field_validator("input_file")
    @classmethod
    def relative_source_file(cls, value: str | None) -> str | None:
        if value is None:
            return None
        path = PurePosixPath(value)
        if (
            value != value.strip()
            or "\0" in value
            or "\\" in value
            or ":" in value
            or path.is_absolute()
            or any(part in {"", ".", ".."} for part in value.split("/"))
            or path.suffix.lower() not in {".csv", ".xlsx"}
        ):
            raise ValueError(
                "input_file must be a relative CSV or XLSX path without traversal"
            )
        return value

    @model_validator(mode="after")
    def source_fields(self) -> DatasetImportRequest:
        if self.source == "existing":
            if (
                self.dataset_id is None
                or self.input_file is not None
                or self.expected_sha256 is not None
            ):
                raise ValueError("Existing imports require only dataset_id")
        elif self.source == "file":
            if self.input_file is None or self.dataset_id is not None:
                raise ValueError(
                    "File imports require input_file and optional expected_sha256"
                )
        elif self.dataset_id is not None or self.input_file is not None:
            raise ValueError("Official imports accept only an optional expected_sha256")
        return self


class TrainingRunRequest(StrictRequest):
    dataset_id: Digest
    mode: Literal["train", "existing"] = "train"
    run_id: Digest | None = None
    config: dict[str, Any] | None = None

    @field_validator("config")
    @classmethod
    def training_configuration(
        cls, value: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if value is None:
            return None
        try:
            _finite_json(value)
            return phase3_config(value).to_dict()
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(
                "Invalid training configuration; check chronological protocol settings"
            ) from exc

    @model_validator(mode="after")
    def mode_fields(self) -> TrainingRunRequest:
        if self.mode == "existing":
            if self.run_id is None or self.config is not None:
                raise ValueError(
                    "Existing training runs require run_id and no configuration"
                )
        elif self.run_id is not None:
            raise ValueError("New training runs do not accept run_id")
        return self


class ForecastRequest(StrictRequest):
    run_id: Digest
    scope: Literal["one_week", "retrospective"] = "one_week"


class InventoryScenarioRequest(StrictRequest):
    forecast_id: Identifier
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("config")
    @classmethod
    def inventory_configuration(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            _finite_json(value)
            return ScenarioConfig.from_dict(value).to_dict()
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(
                "Invalid inventory configuration; check documented parameters and constraints"
            ) from exc
