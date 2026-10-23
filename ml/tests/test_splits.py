import json

import pandas as pd
import pytest

from ml.evaluation.splits import Phase2Config, expanding_folds, monday, split_manifest


def test_default_split_dates_and_expanding_fold_coverage():
    config = Phase2Config()
    manifest = split_manifest(config)
    assert manifest["training"]["weeks"] == 32
    assert manifest["validation"]["weeks"] == 12
    assert manifest["test"]["weeks"] == 8
    assert manifest["test"]["status"] == "reserved_unread_unevaluated"
    folds = expanding_folds(config)
    assert [fold.train_end.date().isoformat() for fold in folds] == [
        "2011-07-11",
        "2011-08-08",
        "2011-09-05",
    ]
    actual = []
    for fold in folds:
        assert fold.train_start == pd.Timestamp(config.start_week)
        assert (
            fold.train_end
            < fold.validation_start
            <= fold.validation_end
            < config.test_start
        )
        actual.extend(
            pd.date_range(fold.validation_start, fold.validation_end, freq="W-MON")
        )
    assert actual == list(
        pd.date_range(config.validation_start, config.validation_end, freq="W-MON")
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"top_products": 0},
        {"top_products": True},
        {"n_folds": 13},
        {"moving_window": 100},
        {"seasonal_period": 52},
        {"train_end": "2011-10-03"},
        {"start_week": "2010-12-07"},
        {"test_end": "2011-10-03"},
        {"min_history_weeks": -1},
        {"seasonal_indicators": {"bad name": [1]}},
        {"seasonal_indicators": {"year_end": [54]}},
    ],
)
def test_invalid_config_fails_before_data_read(changes):
    with pytest.raises(ValueError):
        Phase2Config(**changes)


@pytest.mark.parametrize(
    "value",
    [
        None,
        0,
        True,
        pd.Timestamp("2010-12-06").value,
        "invalid",
        "2011-01-03T01:00",
        "2011-01-03T00:00Z",
        "2011-01-04",
    ],
)
def test_week_boundary_validation(value):
    with pytest.raises(ValueError):
        monday(value)


def test_remainder_folds_are_nonoverlapping_and_config_roundtrips(tmp_path):
    config = Phase2Config(n_folds=5, seasonal_indicators={"year_end": [52, 51, 52]})
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config.to_dict()))
    assert Phase2Config.from_file(path) == config
    assert config.seasonal_indicators == {"year_end": [51, 52]}
    assert [
        (fold.validation_end - fold.validation_start).days // 7 + 1
        for fold in expanding_folds(config)
    ] == [3, 3, 2, 2, 2]
    path.write_text('{"unknown": 1}')
    with pytest.raises(ValueError, match="configuration"):
        Phase2Config.from_file(path)
