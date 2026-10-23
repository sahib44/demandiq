"""Phase 3 protocol configuration; no tuning is allowed after final-test access."""

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ml.evaluation.splits import Phase2Config, expanding_folds, monday


@dataclass(frozen=True)
class Phase3Config:
    timeline: Phase2Config = field(default_factory=Phase2Config)
    seed: int = 42
    warmup_weeks: int = 12
    interval_coverage: float = 0.8
    interval_scale_floor: float = 10.0

    def __post_init__(self) -> None:
        if isinstance(self.timeline, dict):
            object.__setattr__(self, "timeline", Phase2Config(**self.timeline))
        if not isinstance(self.timeline, Phase2Config) or self.timeline.n_folds < 3:
            raise ValueError("Phase 3 requires at least three chronological folds")
        if type(self.seed) is not int or not 0 <= self.seed <= 2**32 - 1:
            raise ValueError("seed must be a nonnegative uint32 integer")
        train_weeks = (
            monday(self.timeline.train_end) - monday(self.timeline.start_week)
        ).days // 7 + 1
        if (
            type(self.warmup_weeks) is not int
            or not 12 <= self.warmup_weeks < train_weeks
        ):
            raise ValueError(
                "warmup_weeks must be >=12 and leave training observations"
            )
        if (
            isinstance(self.interval_coverage, bool)
            or not isinstance(self.interval_coverage, int | float)
            or not 0 < self.interval_coverage < 1
        ):
            raise ValueError("interval_coverage must be between zero and one")
        if (
            isinstance(self.interval_scale_floor, bool)
            or not isinstance(self.interval_scale_floor, int | float)
            or not math.isfinite(self.interval_scale_floor)
            or self.interval_scale_floor <= 0
        ):
            raise ValueError("interval_scale_floor must be finite and positive")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_file(cls, path: Path) -> "Phase3Config":
        try:
            value = json.loads(Path(path).read_text())
            if not isinstance(value, dict):
                raise ValueError("Phase 3 configuration must be a JSON object")
            return cls(**value)
        except (OSError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("Could not load Phase 3 configuration") from exc

    def roles(self) -> dict[str, Any]:
        folds = expanding_folds(self.timeline)
        return {
            "selection_folds": [fold.fold for fold in folds[:-1]],
            "calibration_fold": folds[-1].fold,
            "selection_end": folds[-2].validation_end.date().isoformat(),
            "calibration_start": folds[-1].validation_start.date().isoformat(),
            "calibration_end": folds[-1].validation_end.date().isoformat(),
            "test_start": self.timeline.test_start.date().isoformat(),
            "test_end": self.timeline.test_end,
        }
