"""Explicit chronological blocks and expanding validation windows."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd


def monday(value: Any, field_name: str = "week") -> pd.Timestamp:
    """Require a naive Monday at midnight; never infer weekly alignment."""
    if isinstance(value, int | float | bool):
        raise ValueError(f"{field_name} must be a Monday date, not numeric nanoseconds")
    try:
        result = pd.Timestamp(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(f"{field_name} must be a Monday date") from exc
    if (
        pd.isna(result)
        or result.tzinfo is not None
        or result.dayofweek != 0
        or result != result.normalize()
    ):
        raise ValueError(f"{field_name} must be a naive Monday at midnight")
    return result


@dataclass(frozen=True)
class Phase2Config:
    start_week: str = "2010-12-06"
    train_end: str = "2011-07-11"
    validation_end: str = "2011-10-03"
    test_end: str = "2011-11-28"
    top_products: int = 50
    n_folds: int = 3
    min_history_weeks: int = 12
    seasonal_period: int = 4
    moving_window: int = 4
    seasonal_indicators: dict[str, list[int]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        dates = [
            monday(getattr(self, key), key)
            for key in ("start_week", "train_end", "validation_end", "test_end")
        ]
        if not dates[0] <= dates[1] < dates[2] < dates[3]:
            raise ValueError(
                "Require start_week <= train_end < validation_end < test_end"
            )
        for key in (
            "top_products",
            "n_folds",
            "min_history_weeks",
            "seasonal_period",
            "moving_window",
        ):
            if type(getattr(self, key)) is not int or getattr(self, key) < 1:
                raise ValueError(f"{key} must be a positive integer")
        train_weeks = (dates[1] - dates[0]).days // 7 + 1
        validation_weeks = (dates[2] - dates[1]).days // 7
        if train_weeks < max(
            self.min_history_weeks, self.seasonal_period, self.moving_window
        ):
            raise ValueError(
                "Training history is shorter than the configured history requirements"
            )
        if self.n_folds > validation_weeks:
            raise ValueError(
                "Each expanding fold must contain at least one validation week"
            )
        if not isinstance(self.seasonal_indicators, dict):
            raise ValueError("seasonal_indicators must map names to ISO week numbers")
        for name, weeks in self.seasonal_indicators.items():
            if (
                not isinstance(name, str)
                or not re.fullmatch(r"[a-z][a-z0-9_]{0,47}", name)
                or not isinstance(weeks, list)
                or any(type(w) is not int or not 1 <= w <= 53 for w in weeks)
            ):
                raise ValueError(
                    "seasonal_indicators requires identifier names and ISO weeks 1..53"
                )
        # Canonical date strings and a detached map avoid caller-side mutation.
        for key, value in zip(
            ("start_week", "train_end", "validation_end", "test_end"),
            dates,
            strict=True,
        ):
            object.__setattr__(self, key, value.date().isoformat())
        object.__setattr__(
            self,
            "seasonal_indicators",
            {
                name: sorted(set(weeks))
                for name, weeks in sorted(self.seasonal_indicators.items())
            },
        )

    @property
    def validation_start(self) -> pd.Timestamp:
        return monday(self.train_end) + pd.Timedelta(weeks=1)

    @property
    def test_start(self) -> pd.Timestamp:
        return monday(self.validation_end) + pd.Timedelta(weeks=1)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_file(cls, path: Path) -> Phase2Config:
        try:
            value = json.loads(Path(path).read_text())
            if not isinstance(value, dict):
                raise ValueError("Configuration must be a JSON object")
            return cls(**value)
        except (OSError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError(
                "Could not load Phase 2 configuration; verify fields and JSON"
            ) from exc


@dataclass(frozen=True)
class Fold:
    fold: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    validation_start: pd.Timestamp
    validation_end: pd.Timestamp

    def to_dict(self) -> dict[str, Any]:
        return {
            key: value.date().isoformat() if isinstance(value, pd.Timestamp) else value
            for key, value in asdict(self).items()
        }


def expanding_folds(config: Phase2Config) -> list[Fold]:
    """Partition validation into ordered nonoverlapping blocks, training expands.

    Remainder weeks go to earlier folds. Every validation origin remains inside
    validation; this function never returns or samples a test target.
    """
    weeks = pd.date_range(config.validation_start, config.validation_end, freq="W-MON")
    width, remainder = divmod(len(weeks), config.n_folds)
    cursor = 0
    folds = []
    for number in range(1, config.n_folds + 1):
        count = width + (number <= remainder)
        block = weeks[cursor : cursor + count]
        folds.append(
            Fold(
                number,
                monday(config.start_week),
                block[0] - pd.Timedelta(weeks=1),
                block[0],
                block[-1],
            )
        )
        cursor += count
    return folds


def split_manifest(config: Phase2Config) -> dict[str, Any]:
    def block(start: Any, end: Any) -> dict[str, Any]:
        weeks = pd.date_range(start, end, freq="W-MON")
        return {
            "start_week": weeks[0].date().isoformat(),
            "end_week": weeks[-1].date().isoformat(),
            "weeks": len(weeks),
            "exclusive_timestamp_end": (weeks[-1] + pd.Timedelta(weeks=1))
            .date()
            .isoformat(),
        }

    return {
        "week_convention": "Monday 00:00 inclusive through next Monday 00:00 exclusive; naive London wall time",
        "training": block(config.start_week, config.train_end),
        "validation": block(config.validation_start, config.validation_end),
        "test": {
            **block(config.test_start, config.test_end),
            "status": "reserved_unread_unevaluated",
        },
        "folds": [fold.to_dict() for fold in expanding_folds(config)],
        "evaluation_protocol": "one-week-ahead rolling origin: observe prior completed validation weeks; rank products once per fold using its training only",
    }
