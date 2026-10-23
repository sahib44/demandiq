"""Real XLSX/CSV/Parquet IO using clearly synthetic transactions."""

import csv
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import Workbook

from ml.data.acquisition import sha256_file
from ml.data.io import InputError, read_transactions
from ml.pipelines import ingestion

HEADERS = [
    "InvoiceNo",
    "StockCode",
    "Description",
    "Quantity",
    "InvoiceDate",
    "UnitPrice",
    "CustomerID",
    "Country",
]
SYNTHETIC_CUSTOMER = "synthetic-customer-alpha"


def sample_rows():
    # All identifiers and transactions are test-only, never copied from UCI.
    return [
        [
            "TEST-1",
            "00001",
            "SYNTHETIC ITEM",
            3,
            datetime(2011, 1, 3, 9),
            2.5,
            SYNTHETIC_CUSTOMER,
            "Testland",
        ],
        [
            "C-TEST-2",
            "00001",
            "SYNTHETIC ITEM",
            -1,
            datetime(2011, 1, 4, 9),
            2.5,
            None,
            "Testland",
        ],
        ["TEST-3", "00001", None, -1, datetime(2011, 1, 5, 9), 2.5, None, None],
        [
            "TEST-4",
            "00002",
            "SECOND SYNTHETIC ITEM",
            4,
            datetime(2011, 1, 6, 9),
            1.0,
            SYNTHETIC_CUSTOMER,
            "Testland",
        ],
    ]


def write_workbook(path, rows=None, headers=None):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(headers if headers is not None else HEADERS)
    for row in rows if rows is not None else sample_rows():
        sheet.append(row)
    workbook.save(path)
    workbook.close()


def test_xlsx_ingestion_conservation_privacy_and_roundtrip(tmp_path):
    source = tmp_path / "synthetic.xlsx"
    write_workbook(source, sample_rows() + [sample_rows()[0]])
    result = ingestion.ingest_dataset(source, tmp_path / "processed")
    assert result.report["original_rows"] == 5
    assert result.report["duplicate_rows"] == 1
    assert result.report["cleaned_rows"] == 4
    assert result.report["purchase_rows"] == 2
    assert result.report["cancellation_rows"] == 1
    assert result.report["return_rows"] == 1
    frames = [
        pd.read_parquet(result.dataset_dir / f"{name}.parquet")
        for name in ingestion.PARTITIONS
    ]
    assert sum(map(len, frames)) == 4
    assert set(frames[0].stock_code) == {"00001", "00002"}
    for frame in frames:
        assert "CustomerID" not in frame.columns
        assert SYNTHETIC_CUSTOMER not in frame.to_json()
        assert str(frame.invoice_date.dtype) == "datetime64[ns]"
        assert str(frame.quantity.dtype) == "int64"
    audit = pd.read_parquet(result.dataset_dir / "audit.parquet")
    assert len(audit) == 5
    assert set(audit.columns) == {"source_row", "disposition", "reasons"}
    assert ingestion.product_catalog(result.dataset_dir) == [
        {"stock_code": "00001", "description": "SYNTHETIC ITEM"},
        {"stock_code": "00002", "description": "SECOND SYNTHETIC ITEM"},
    ]
    assert SYNTHETIC_CUSTOMER not in json.dumps(result.manifest)
    assert SYNTHETIC_CUSTOMER not in json.dumps(result.report)


def test_identical_outputs_in_distinct_directories_and_cache(tmp_path, monkeypatch):
    source = tmp_path / "synthetic.xlsx"
    write_workbook(source)
    first = ingestion.ingest_dataset(source, tmp_path / "first")
    second = ingestion.ingest_dataset(source, tmp_path / "second")
    assert first.manifest == second.manifest
    assert first.report == second.report
    assert (first.dataset_dir / "manifest.json").read_bytes() == (
        second.dataset_dir / "manifest.json"
    ).read_bytes()
    monkeypatch.setattr(
        ingestion,
        "read_transactions",
        lambda _: pytest.fail("complete cache should avoid reparsing"),
    )
    assert ingestion.ingest_dataset(source, tmp_path / "first") == first
    (first.dataset_dir / "purchases.parquet").write_bytes(b"damaged")
    with pytest.raises(ingestion.ArtifactError, match="integrity"):
        ingestion.ingest_dataset(source, tmp_path / "first")


def test_config_and_source_versioning(tmp_path, monkeypatch):
    source = tmp_path / "synthetic.xlsx"
    write_workbook(source)
    first = ingestion.ingest_dataset(source, tmp_path / "processed")
    monkeypatch.setattr(ingestion, "PIPELINE_VERSION", "test-different-version")
    second = ingestion.ingest_dataset(source, tmp_path / "processed")
    assert first.manifest["dataset_id"] != second.manifest["dataset_id"]
    write_workbook(source, sample_rows()[:1])
    third = ingestion.ingest_dataset(source, tmp_path / "processed")
    assert third.manifest["dataset_id"] != second.manifest["dataset_id"]
    assert third.manifest["source_sha256"] == sha256_file(source)


@pytest.mark.parametrize(
    "field,value",
    [
        ("original_rows", 999),
        ("cleaned_rows", 999),
        ("cleaning_version", "wrong"),
        ("artifact_dir", "../elsewhere"),
    ],
)
def test_corrupt_manifest_metadata_refused(tmp_path, field, value):
    source = tmp_path / "synthetic.xlsx"
    write_workbook(source)
    result = ingestion.ingest_dataset(source, tmp_path / "processed")
    manifest = dict(result.manifest)
    manifest[field] = value
    (result.dataset_dir / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ingestion.ArtifactError):
        ingestion.ingest_dataset(source, tmp_path / "processed")


def test_corrupt_artifact_row_metadata_refused(tmp_path):
    source = tmp_path / "synthetic.xlsx"
    write_workbook(source)
    result = ingestion.ingest_dataset(source, tmp_path / "processed")
    manifest = result.manifest
    manifest["artifacts"]["purchases.parquet"]["rows"] = 999
    (result.dataset_dir / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ingestion.ArtifactError, match="row count"):
        ingestion.ingest_dataset(source, tmp_path / "processed")


def test_failed_publication_and_input_change_leave_no_dataset(tmp_path, monkeypatch):
    source = tmp_path / "synthetic.xlsx"
    write_workbook(source)
    original_reader = ingestion.read_transactions

    def changing_reader(path):
        frame = original_reader(path)
        path.write_bytes(b"source modified during read")
        return frame

    monkeypatch.setattr(ingestion, "read_transactions", changing_reader)
    with pytest.raises(InputError, match="changed"):
        ingestion.ingest_dataset(source, tmp_path / "processed")
    assert list((tmp_path / "processed").iterdir()) == []
    monkeypatch.setattr(ingestion, "read_transactions", original_reader)
    write_workbook(source)
    monkeypatch.setattr(
        pd.DataFrame,
        "to_parquet",
        lambda *args, **kw: (_ for _ in ()).throw(OSError("disk full")),
    )
    with pytest.raises(OSError, match="disk full"):
        ingestion.ingest_dataset(source, tmp_path / "processed")
    assert list((tmp_path / "processed").iterdir()) == []


def test_metadata_registration_retry_reuses_complete_files(tmp_path, monkeypatch):
    from backend.app.db import repository

    source = tmp_path / "synthetic.xlsx"
    write_workbook(source)
    calls = []

    def register(url, manifest, report, products):
        calls.append((manifest, report, products))
        if len(calls) == 1:
            raise ConnectionError("synthetic outage")
        return manifest["dataset_id"]

    monkeypatch.setattr(repository, "persist_dataset", register)
    with pytest.raises(ConnectionError):
        ingestion.ingest_dataset(
            source, tmp_path / "processed", database_url="postgresql+psycopg://test"
        )
    monkeypatch.setattr(
        ingestion,
        "read_transactions",
        lambda _: pytest.fail("retry should use published files"),
    )
    ingestion.ingest_dataset(
        source, tmp_path / "processed", database_url="postgresql+psycopg://test"
    )
    assert calls[0] == calls[1]
    assert len(list((tmp_path / "processed").iterdir())) == 1


def test_csv_preserves_leading_zero_ids_and_explicit_day_first_dates(tmp_path):
    source = tmp_path / "synthetic.csv"
    with source.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(HEADERS)
        writer.writerow(
            [
                "001234",
                "00001",
                "SYNTHETIC",
                "2",
                "03/01/2011 09:00",
                "1.25",
                "000007",
                "Testland",
            ]
        )
    result = ingestion.ingest_dataset(source, tmp_path / "processed")
    frame = pd.read_parquet(result.dataset_dir / "purchases.parquet")
    assert frame.iloc[0].invoice_no == "001234"
    assert frame.iloc[0].stock_code == "00001"
    assert frame.iloc[0].invoice_date == pd.Timestamp("2011-01-03 09:00")


@pytest.mark.parametrize("extension", [".xlsx", ".csv"])
def test_duplicate_headers_not_silently_mangled(tmp_path, extension):
    source = tmp_path / f"synthetic{extension}"
    headers = HEADERS + ["Quantity"]
    if extension == ".xlsx":
        write_workbook(source, rows=[], headers=headers)
    else:
        source.write_text(",".join(headers) + "\n")
    frame = read_transactions(source)
    assert frame.columns.duplicated().any()
    with pytest.raises(ValueError, match="[Dd]uplicate"):
        ingestion.ingest_dataset(source, tmp_path / "processed")
    assert list((tmp_path / "processed").iterdir()) == []


def test_unsupported_missing_or_malformed_input(tmp_path):
    with pytest.raises(InputError, match="formats"):
        ingestion.ingest_dataset(tmp_path / "input.txt", tmp_path / "out")
    with pytest.raises(InputError, match="missing"):
        ingestion.ingest_dataset(tmp_path / "missing.xlsx", tmp_path / "out")
    empty = tmp_path / "empty.csv"
    empty.write_text("")
    with pytest.raises(InputError, match="header"):
        read_transactions(empty)
    empty.write_text("a,b\n1\n")
    with pytest.raises(InputError, match="field count"):
        read_transactions(empty)
    invalid = tmp_path / "broken.xlsx"
    invalid.write_bytes(b"invalid workbook container")
    with pytest.raises(InputError, match="Could not read"):
        read_transactions(invalid)


def test_cli_emits_only_safe_counts_and_fails_usefully(tmp_path):
    source = tmp_path / "synthetic.xlsx"
    write_workbook(source)
    root = Path(__file__).resolve().parents[2]
    environment = {**os.environ, "PYTHONPATH": str(root)}
    args = [
        sys.executable,
        str(root / "scripts/ingest_data.py"),
        "--input",
        str(source),
        "--output-dir",
        str(tmp_path / "out"),
    ]
    completed = subprocess.run(
        args, capture_output=True, text=True, env=environment, check=False
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["original_rows"] == 4
    assert SYNTHETIC_CUSTOMER not in completed.stdout + completed.stderr
    source.unlink()
    failed = subprocess.run(
        args, capture_output=True, text=True, env=environment, check=False
    )
    assert failed.returncode == 1
    assert "missing or unreadable" in json.loads(failed.stderr)["error"]
    write_workbook(source, rows=[], headers=["InvoiceNo"])
    invalid_schema = subprocess.run(
        args, capture_output=True, text=True, env=environment, check=False
    )
    assert invalid_schema.returncode == 1
    assert "missing required fields" in json.loads(invalid_schema.stderr)["error"]
