"""Synthetic-only transaction fixtures; no real UCI customer rows are committed."""

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from ml.data.cleaning import (
    AUDIT_DTYPES,
    CUSTOMER_HASH_DOMAIN,
    INT64_MAX,
    INT64_MIN,
    NONMERCHANDISE_CODES,
    TRANSACTION_DTYPES,
    clean_transactions,
)
from ml.data.schema import SOURCE_COLUMNS, SchemaValidationError, validate_input


def row(**changes):
    """One explicitly synthetic eligible purchase, overridden per case."""
    return {
        "InvoiceNo": "SYNTH-1001",
        "StockCode": "SYNTH-A1",
        "Description": "Synthetic item",
        "Quantity": 2,
        "InvoiceDate": datetime(2011, 2, 1, 10, 30),
        "UnitPrice": 3.25,
        "CustomerID": "SYNTHETIC-CUSTOMER-001",
        "Country": "Synthetic country",
    } | changes


def clean(*rows):
    return clean_transactions(pd.DataFrame(rows, columns=SOURCE_COLUMNS))


def reason_set(result, source_row=1):
    text = result.audit.loc[result.audit.source_row.eq(source_row), "reasons"].iloc[0]
    return set(text.split("|")) if text else set()


@pytest.mark.parametrize("source", [None, [], {}, np.array([1])])
def test_schema_requires_dataframe(source):
    with pytest.raises(SchemaValidationError, match="DataFrame"):
        validate_input(source)


def test_schema_rejects_missing_extra_and_duplicate_columns_without_cell_values():
    with pytest.raises(SchemaValidationError, match="Quantity"):
        validate_input(pd.DataFrame([row()]).drop(columns="Quantity"))
    with pytest.raises(SchemaValidationError, match="unexpected field count 1"):
        validate_input(pd.DataFrame([row()]).assign(secret="SYNTHETIC-SECRET"))
    duplicate = pd.DataFrame([[1] * 8], columns=["InvoiceNo"] * 8)
    with pytest.raises(SchemaValidationError, match="Duplicate"):
        validate_input(duplicate)
    multi = pd.DataFrame([row()])
    multi.columns = pd.MultiIndex.from_tuples([(name, "x") for name in multi.columns])
    with pytest.raises(SchemaValidationError, match="flat"):
        validate_input(multi)


def test_schema_permits_reordered_columns_and_invalid_scalar_for_row_quarantine():
    source = pd.DataFrame([row(Quantity="unknown")])[list(reversed(SOURCE_COLUMNS))]
    validate_input(source)
    result = clean_transactions(source)
    assert result.report["rejected_rows"] == 1
    assert "invalid_quantity" in reason_set(result)


def test_all_dispositions_conserve_rows_and_stages_reconcile():
    result = clean(
        row(),
        row(),
        row(InvoiceNo="C-SYNTH-2", Quantity=-2),
        row(InvoiceNo="SYNTH-3", Quantity=-1),
        row(InvoiceNo="C-SYNTH-4", Quantity=2),
        row(InvoiceNo="SYNTH-5", UnitPrice=0),
    )
    assert result.audit.disposition.tolist() == [
        "purchase",
        "duplicate",
        "cancellation",
        "return",
        "rejected",
        "rejected",
    ]
    report = result.report
    assert report["original_rows"] == 6
    assert report["cleaned_rows"] == 3
    assert report["duplicate_rows"] == 1
    assert report["rejected_rows"] == 2
    assert (
        report["purchase_rows"]
        == report["cancellation_rows"]
        == report["return_rows"]
        == 1
    )
    assert "cancellation_sign_mismatch" in reason_set(result, 5)
    assert result.cancellations.quantity.tolist() == [-2]
    assert result.returns.quantity.tolist() == [-1]
    stages = report["stages"]
    for before, after in zip(stages, stages[1:], strict=False):
        assert before["after"] == after["before"]
    for stage in stages:
        assert stage["before"] - stage["removed"] == stage["after"]


def test_deduplication_happens_before_whitespace_and_numeric_normalization():
    result = clean(
        row(InvoiceNo="1001", CustomerID="100", Quantity="2"),
        row(InvoiceNo=" 1001 ", CustomerID="100.0", Quantity="2"),
        row(InvoiceNo="1001", CustomerID="100", Quantity="2"),
    )
    assert result.report["duplicate_rows"] == 1
    assert result.purchases.source_row.tolist() == [1, 2]
    assert result.purchases.invoice_no.tolist() == ["1001", "1001"]
    assert result.purchases.customer_key.nunique() == 1
    assert result.audit.iloc[2].reasons == "exact_source_duplicate"


def test_booleans_are_not_deduplicated_as_valid_numeric_values():
    source = pd.DataFrame([row(Quantity=1), row(Quantity=True)], dtype=object)
    result = clean_transactions(source)
    assert result.report["duplicate_rows"] == 0
    assert result.report["purchase_rows"] == 1
    assert result.report["rejected_rows"] == 1


@pytest.mark.parametrize(
    "value",
    [
        0,
        1.5,
        "0",
        "2.2",
        None,
        np.nan,
        np.inf,
        -np.inf,
        True,
        False,
        "?",
        "1_000",
        2**63,
        str(-(2**63) - 1),
        [],
        {},
        complex(2, 0),
    ],
)
def test_invalid_quantities_quarantined(value):
    result = clean(row(Quantity=value))
    assert result.report["invalid_quantities"] == 1
    assert result.report["rejected_rows"] == 1
    assert "invalid_quantity" in reason_set(result)
    assert result.purchases.empty


@pytest.mark.parametrize(
    "value",
    [
        INT64_MAX,
        str(INT64_MAX),
        INT64_MIN,
        str(INT64_MIN),
        " 2 ",
        Decimal("2.00"),
        2_000_000,
    ],
)
def test_integral_quantity_boundaries_and_large_outliers_preserved(value):
    result = clean(row(Quantity=value))
    accepted = pd.concat([result.purchases, result.returns])
    assert accepted.quantity.tolist() == [int(value)]
    assert str(accepted.quantity.dtype) == "int64"


@pytest.mark.parametrize(
    "value",
    [
        0,
        -1,
        None,
        np.nan,
        np.inf,
        -np.inf,
        True,
        False,
        "bad",
        "NaN",
        "1e9999",
        "1e-9999",
        [],
        complex(1, 0),
    ],
)
def test_invalid_prices_quarantined(value):
    result = clean(row(UnitPrice=value))
    assert result.report["invalid_prices"] == 1
    assert result.report["rejected_rows"] == 1
    assert "invalid_price" in reason_set(result)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (datetime(2011, 2, 1, 10, 30), "2011-02-01T10:30:00"),
        (pd.Timestamp("2011-02-01 10:30:00"), "2011-02-01T10:30:00"),
        (np.datetime64("2011-02-01T10:30"), "2011-02-01T10:30:00"),
        ("2011-02-01", "2011-02-01T00:00:00"),
        ("2011-02-01T10:30:05.123456", "2011-02-01T10:30:05.123456"),
        ("01/02/2011", "2011-02-01T00:00:00"),
        ("01/02/2011 10:30", "2011-02-01T10:30:00"),
        ("01/02/2011 10:30:05", "2011-02-01T10:30:05"),
        (" 2011-02-01 10:30 ", "2011-02-01T10:30:00"),
    ],
)
def test_dates_use_explicit_formats_and_remain_naive(value, expected):
    result = clean(row(InvoiceDate=value))
    assert result.purchases.invoice_date.iloc[0].isoformat() == expected
    assert str(result.purchases.invoice_date.dtype) == "datetime64[ns]"
    if isinstance(value, str):
        assert {"date_parsed_day_first", "date_parsed_iso"} & reason_set(result)


@pytest.mark.parametrize(
    "value",
    [
        None,
        pd.NaT,
        np.datetime64("NaT"),
        "02/01/11",
        "02-01-2011",
        "2011-02-30",
        "13/31/2011",
        "2011-02-01Z",
        "2011-02-01T10:30+00:00",
        datetime(2011, 2, 1, tzinfo=UTC),
        "9999-02-01",
        40575,
        True,
        [],
        "tomorrow",
    ],
)
def test_invalid_or_timezone_dates_quarantined(value):
    result = clean(row(InvoiceDate=value))
    assert result.report["invalid_dates"] == 1
    assert result.report["rejected_rows"] == 1
    assert "invalid_date" in reason_set(result)


@pytest.mark.parametrize("field", ["InvoiceNo", "StockCode"])
@pytest.mark.parametrize("value", [None, np.nan, "", "  ", True, 1.5, [], {}])
def test_required_identifiers_missing_or_invalid_are_quarantined(field, value):
    result = clean(row(**{field: value}))
    assert result.report["rejected_rows"] == 1
    expected = "invoice_id" if field == "InvoiceNo" else "product_id"
    assert {f"missing_{expected}", f"invalid_{expected}"} & reason_set(result)


def test_missing_optional_values_retained_and_counted_after_deduplication():
    source = row(Description=None, CustomerID=np.nan, Country=" ")
    result = clean(source, source)
    assert result.report["purchase_rows"] == 1
    assert result.report["missing_descriptions"] == 1
    assert result.report["missing_customer_ids"] == 1
    assert result.report["missing_countries"] == 1
    assert result.purchases.description.isna().all()
    assert result.purchases.customer_key.isna().all()
    assert result.purchases.country.isna().all()
    assert result.report["unique_customers"] == 0


def test_invalid_optional_scalar_values_are_null_and_flagged():
    result = clean(row(Description=123, CustomerID=True, Country=[]))
    assert result.report["purchase_rows"] == 1
    assert {
        "invalid_description",
        "invalid_customer_id",
        "invalid_country",
    } <= reason_set(result)
    assert (
        result.purchases[["description", "customer_key", "country"]].isna().all().all()
    )


def test_numeric_ids_trimmed_values_and_lowercase_cancellation_are_audited():
    result = clean(
        row(
            InvoiceNo=" c1001 ",
            StockCode=123.0,
            Description=" Item ",
            Quantity=" -2 ",
            UnitPrice=" 3.25 ",
            CustomerID=456.0,
            Country=" Example ",
        )
    )
    accepted = result.cancellations.iloc[0]
    assert accepted.invoice_no == "C1001"
    assert accepted.stock_code == "123"
    assert accepted.description == "Item"
    assert accepted.country == "Example"
    assert (
        accepted.customer_key
        == hashlib.sha256(CUSTOMER_HASH_DOMAIN + b"456").hexdigest()
    )
    assert {
        "invoice_id_trimmed",
        "invoice_prefix_normalized",
        "product_id_numeric_normalized",
        "description_trimmed",
        "quantity_trimmed",
        "quantity_numeric_coerced",
        "price_trimmed",
        "price_numeric_coerced",
        "customer_id_numeric_normalized",
        "customer_pseudonymized",
        "country_trimmed",
        "classified_cancellation",
    } <= reason_set(result)


@pytest.mark.parametrize("code", sorted(NONMERCHANDISE_CODES))
def test_explicit_nonmerchandise_codes_quarantined_case_insensitively(code):
    result = clean(row(StockCode=f" {code.lower()} "))
    assert result.report["rejected_rows"] == 1
    assert "nonmerchandise_code" in reason_set(result)


def test_alphanumeric_merchandise_codes_not_removed():
    result = clean(row(StockCode="SYNTH-ABC"), row(StockCode="12345A"))
    assert result.report["purchase_rows"] == 2


def test_product_identifier_length_matches_database_boundary():
    result = clean(row(StockCode="A" * 128), row(StockCode="A" * 129))
    assert result.purchases.stock_code.tolist() == ["A" * 128]
    assert result.report["rejected_rows"] == 1
    assert result.report["invalid_product_ids"] == 1
    assert result.report["missing_product_ids"] == 0
    assert {"invalid_product_id", "product_id_too_long"} <= reason_set(result, 2)
    assert result.report["reason_counts"]["product_id_too_long"] == 1
    assert "128" in result.report["policies"]["product_identifiers"]


@pytest.mark.parametrize("field", ["Quantity", "UnitPrice"])
@pytest.mark.parametrize(
    "value",
    [Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity"), "1e999999999999999999999"],
)
def test_nonfinite_decimals_and_unrepresentable_exponents_quarantined(field, value):
    result = clean(row(**{field: value}))
    assert result.report["rejected_rows"] == 1
    expected = "invalid_quantity" if field == "Quantity" else "invalid_price"
    assert expected in reason_set(result)


@pytest.mark.parametrize(
    "value",
    [
        "2011-02-01 24:00",
        "2011-02-01T10:30:60",
        "29/02/2011",
        "2300-01-01",
        "2011-02-01T10:30:00.1234567",
    ],
)
def test_dates_reject_invalid_clock_calendar_and_unsupported_precision(value):
    result = clean(row(InvoiceDate=value))
    assert result.report["rejected_rows"] == 1
    assert result.report["invalid_dates"] == 1


def test_quantity_exponents_stay_exact_at_int64_boundary():
    result = clean(row(Quantity="9.223372036854775807e18"))
    assert result.purchases.quantity.tolist() == [INT64_MAX]
    assert "quantity_numeric_coerced" in reason_set(result)


def test_reproducibility_typed_empty_outputs_and_privacy():
    source = pd.DataFrame([row(), row(UnitPrice=0), row(Quantity=-1)])
    source.index = [91, 81, 71]
    before = source.copy(deep=True)
    first = clean_transactions(source)
    second = clean_transactions(source)
    assert_frame_equal(source, before)
    for attr in ("purchases", "cancellations", "returns", "audit"):
        assert_frame_equal(getattr(first, attr), getattr(second, attr))
    assert first.report == second.report
    json.dumps(first.report, allow_nan=False, sort_keys=True)
    assert list(first.audit.columns) == list(AUDIT_DTYPES)
    assert first.audit.source_row.tolist() == [1, 2, 3]
    assert "SYNTHETIC-CUSTOMER-001" not in first.purchases.to_json()
    assert "SYNTHETIC-CUSTOMER-001" not in first.audit.to_json()
    assert "SYNTHETIC-CUSTOMER-001" not in json.dumps(first.report)
    assert "CustomerID" not in first.purchases.columns
    for partition in (first.purchases, first.cancellations, first.returns):
        assert partition.dtypes.astype(str).to_dict() == TRANSACTION_DTYPES
    assert first.audit.dtypes.astype(str).to_dict() == AUDIT_DTYPES


def test_empty_source_still_has_typed_schemas_and_json_report():
    result = clean_transactions(pd.DataFrame(columns=SOURCE_COLUMNS))
    assert result.report["original_rows"] == result.report["cleaned_rows"] == 0
    assert result.report["date_range"] == {"start": None, "end": None}
    assert result.report["countries"] == []
    for partition in (result.purchases, result.cancellations, result.returns):
        assert partition.dtypes.astype(str).to_dict() == TRANSACTION_DTYPES
    assert result.audit.dtypes.astype(str).to_dict() == AUDIT_DTYPES
    json.dumps(result.report, allow_nan=False)


def test_summary_coverage_entities_and_reason_counts_match_audit():
    result = clean(
        row(),
        row(
            InvoiceNo="C-SYNTH-2",
            Quantity=-1,
            InvoiceDate="2011-03-01",
            Country="Another synthetic country",
        ),
        row(InvoiceNo="SYNTH-3", Quantity=-2, StockCode="SYNTH-B2", CustomerID=None),
        row(UnitPrice=0),
    )
    report = result.report
    assert report["date_range"] == {
        "start": "2011-02-01T10:30:00",
        "end": "2011-03-01T00:00:00",
    }
    assert report["unique_products"] == 2
    assert report["unique_invoices"] == 3
    assert report["unique_customers"] == 1
    assert report["unique_countries"] == 2
    for code, count in report["reason_counts"].items():
        assert count == sum(code in codes.split("|") for codes in result.audit.reasons)
