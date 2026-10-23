"""Public fictional demo boundaries; official results are never accessed."""

import csv
from pathlib import Path

import pytest

from ml.pipelines.ingestion import ingest_dataset
from scripts.demo_synthetic import prepare_synthetic_demo


def test_public_fixture_has_no_customer_data_and_audits_bad_rows(tmp_path):
    source = Path("fixtures/synthetic_retail.csv")
    with source.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 175
    assert {r["StockCode"] for r in rows} == {"SYNTH-1", "SYNTH-2", "SYNTH-3"}
    assert all(not r["CustomerID"] and r["Country"] == "Synthetic" for r in rows)
    result = ingest_dataset(source, tmp_path / "processed")
    assert result.report["duplicate_rows"] == 1
    assert result.report["rejected_rows"] == 1
    assert result.report["original_rows"] == 175


@pytest.mark.parametrize(
    "path", ["data", "artifacts", "data/evaluation-ledger", ".cache"]
)
def test_demo_refuses_official_or_nonisolated_output(path):
    with pytest.raises(ValueError, match="subdirectory of .cache"):
        prepare_synthetic_demo(Path(path))
