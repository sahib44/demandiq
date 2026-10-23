"""Deterministic, auditable cleaning of UCI Online Retail transaction rows.

Only valid merchandise movements enter the three accepted partitions. Cancellation
signals are not matched to purchases: a C-prefixed negative movement is a
cancellation, and a negative movement without that prefix is a return. Credits
with positive quantities are quarantined because the movement sign is uncertain.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from numbers import Integral, Real
from typing import Any, Final

import numpy as np
import pandas as pd

from ml.data.schema import SOURCE_COLUMNS, validate_input

CLEANING_VERSION: Final = "1.0.1"
PRODUCT_ID_MAX_LENGTH: Final = 128
# Explicitly excluded accounting, postage, fee and manual-adjustment codes. A code
# containing letters is otherwise eligible; no generic numeric-only rule is used.
NONMERCHANDISE_CODES: Final = frozenset(
    {"POST", "D", "M", "C2", "DOT", "BANK CHARGES", "AMAZONFEE", "CRUK", "S"}
)
CUSTOMER_HASH_DOMAIN: Final = b"demandiq:uci-online-retail:customer:v1\0"
INT64_MIN: Final = -(2**63)
INT64_MAX: Final = 2**63 - 1
_NUMERIC = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
_INTEGER_ID = re.compile(r"^[+-]?\d+(?:\.0+)?$")
_ISO_DATE = re.compile(
    r"^\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?)?$"
)
_DAY_FIRST_DATE = re.compile(r"^\d{2}/\d{2}/\d{4}(?: \d{2}:\d{2}(?::\d{2})?)?$")

TRANSACTION_DTYPES: Final = {
    "source_row": "int64",
    "invoice_no": "string",
    "stock_code": "string",
    "description": "string",
    "quantity": "int64",
    "invoice_date": "datetime64[ns]",
    "unit_price": "float64",
    "customer_key": "string",
    "country": "string",
}
AUDIT_DTYPES: Final = {
    "source_row": "int64",
    "disposition": "string",
    "reasons": "string",
}


@dataclass(frozen=True)
class CleanResult:
    """Typed accepted movements, row decisions and a JSON-serializable summary.

    ``source_row`` is the 1-based data row position, independent of the input index.
    Customer pseudonyms are linkable and remain sensitive local data. The audit
    contains only row positions, dispositions and reason codes; rejected source
    values and original customer IDs are never returned.
    """

    purchases: pd.DataFrame
    cancellations: pd.DataFrame
    returns: pd.DataFrame
    audit: pd.DataFrame
    report: dict[str, Any]


def _missing(value: Any) -> bool:
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, float | np.floating):
        return math.isnan(value)
    if isinstance(value, datetime | date | np.datetime64):
        return bool(pd.isna(value))
    return False


def _source_key(value: Any, source_row: int) -> tuple[Any, ...]:
    """Typed source identity: no whitespace/ID/date coercion before deduplication."""
    if value is None or value is pd.NA or value is pd.NaT:
        return ("null",)
    if isinstance(value, str):
        return ("str", value)
    if isinstance(value, bool | np.bool_):
        return ("bool", bool(value))
    if isinstance(value, Integral):
        return ("integer", int(value))
    if isinstance(value, Real):
        return ("real", "nan" if math.isnan(value) else float(value))
    if isinstance(value, Decimal):
        return ("decimal", str(value))
    if isinstance(value, datetime | date | np.datetime64):
        return ("datetime", str(value))
    # Unsupported objects cannot accidentally hide a later rejected record by
    # sharing a string representation or colliding with a valid scalar.
    return ("unsupported", source_row)


def _identifier(value: Any, field: str, reasons: set[str]) -> str | None:
    if _missing(value):
        reasons.add(f"missing_{field}")
        return None
    if isinstance(value, bool | np.bool_):
        reasons.add(f"invalid_{field}")
        return None
    if isinstance(value, str):
        result = value.strip()
        if result != value:
            reasons.add(f"{field}_trimmed")
        if _INTEGER_ID.fullmatch(result) and "." in result:
            result = result[: result.index(".")]
            reasons.add(f"{field}_numeric_normalized")
        return result
    if isinstance(value, Real | Decimal):
        try:
            number = Decimal(str(value))
            if number.is_finite() and number == number.to_integral_value():
                reasons.add(f"{field}_numeric_normalized")
                return str(int(number))
        except (ValueError, InvalidOperation, OverflowError):
            pass
    reasons.add(f"invalid_{field}")
    return None


def _text(value: Any, field: str, reasons: set[str]) -> str | None:
    if _missing(value):
        reasons.add(f"missing_{field}")
        return None
    if not isinstance(value, str):
        reasons.add(f"invalid_{field}")
        return None
    result = value.strip()
    if result != value:
        reasons.add(f"{field}_trimmed")
    return result


def _number(value: Any, field: str, reasons: set[str]) -> Decimal | None:
    if isinstance(value, bool | np.bool_) or _missing(value):
        reasons.add(f"invalid_{field}")
        return None
    if not isinstance(value, str | Real | Decimal):
        reasons.add(f"invalid_{field}")
        return None
    if isinstance(value, str):
        text = value.strip()
        if text != value:
            reasons.add(f"{field}_trimmed")
        if not _NUMERIC.fullmatch(text):
            reasons.add(f"invalid_{field}")
            return None
        reasons.add(f"{field}_numeric_coerced")
    else:
        text = str(value)
    try:
        number = Decimal(text)
    except InvalidOperation:
        reasons.add(f"invalid_{field}")
        return None
    if not number.is_finite():
        reasons.add(f"invalid_{field}")
        return None
    return number


def _quantity(value: Any, reasons: set[str]) -> int | None:
    number = _number(value, "quantity", reasons)
    if number is None:
        return None
    if (
        number != number.to_integral_value()
        or number == 0
        or number < INT64_MIN
        or number > INT64_MAX
    ):
        reasons.add("invalid_quantity")
        return None
    if not isinstance(value, str | Integral):
        reasons.add("quantity_integral_normalized")
    return int(number)


def _price(value: Any, reasons: set[str]) -> float | None:
    number = _number(value, "price", reasons)
    if number is None:
        return None
    price = float(number)
    if number <= 0 or not math.isfinite(price) or price <= 0:
        reasons.add("invalid_price")
        return None
    if not isinstance(value, str | float | np.floating):
        reasons.add("price_float_normalized")
    return price


def _invoice_date(value: Any, reasons: set[str]) -> pd.Timestamp | None:
    parsed: Any = value
    if isinstance(value, str):
        text = value.strip()
        if text != value:
            reasons.add("date_trimmed")
        try:
            if _ISO_DATE.fullmatch(text):
                parsed = datetime.fromisoformat(text)
                reasons.add("date_parsed_iso")
            elif _DAY_FIRST_DATE.fullmatch(text):
                formats = ("%d/%m/%Y", "%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S")
                parsed = datetime.strptime(text, formats[text.count(":")])
                reasons.add("date_parsed_day_first")
            else:
                reasons.add("invalid_date")
                return None
        except ValueError:
            reasons.add("invalid_date")
            return None
    elif not isinstance(value, datetime | date | np.datetime64) or _missing(value):
        reasons.add("invalid_date")
        return None
    try:
        timestamp = pd.Timestamp(parsed)
        if timestamp.tzinfo is not None:
            reasons.add("timezone_aware_date")
            reasons.add("invalid_date")
            return None
        # Force nanosecond range validation instead of allowing pandas' wider
        # lower-resolution timestamp values to fail during output conversion.
        _ = timestamp.value
        if isinstance(value, np.datetime64) or (
            isinstance(value, date) and not isinstance(value, datetime)
        ):
            reasons.add("date_native_normalized")
        return timestamp
    except (ValueError, TypeError, OverflowError):
        reasons.add("invalid_date")
        return None


def _typed_frame(rows: list[dict[str, Any]], dtypes: dict[str, str]) -> pd.DataFrame:
    return pd.DataFrame.from_records(rows, columns=list(dtypes)).astype(dtypes)


def clean_transactions(frame: pd.DataFrame) -> CleanResult:
    """Clean the source without guessing dates, imputing demand or capping outliers.

    Supported date strings are naive ISO ``YYYY-MM-DD[ HH:MM[:SS[.ffffff]]]``
    (also ``T``) and explicit day-first ``DD/MM/YYYY[ HH:MM[:SS]]``. Native
    naive datetimes remain London wall time; no timezone or UTC is inferred.
    Missing optional descriptions, countries and customer IDs are retained with
    flags. Malformed optional scalar values become null with a distinct flag.
    Invalid required values, zero/fractional quantities, nonpositive prices,
    nonmerchandise codes and C-positive sign anomalies are quarantined.

    Quality-flag counts refer to nonduplicate source rows before rejection;
    accepted entity counts and coverage refer to all three accepted partitions.
    The input frame is never modified. A repeat run produces identical content.
    """
    validate_input(frame)
    partitions: dict[str, list[dict[str, Any]]] = {
        "purchase": [],
        "cancellation": [],
        "return": [],
    }
    audit_rows: list[dict[str, Any]] = []
    quality: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    seen: set[tuple[Any, ...]] = set()
    duplicates = 0
    rejected = 0
    for source_row, values in enumerate(
        frame.loc[:, list(SOURCE_COLUMNS)].itertuples(index=False, name=None), start=1
    ):
        source_key = tuple(_source_key(value, source_row) for value in values)
        if source_key in seen:
            duplicates += 1
            audit_rows.append(
                {
                    "source_row": source_row,
                    "disposition": "duplicate",
                    "reasons": "exact_source_duplicate",
                }
            )
            reason_counts["exact_source_duplicate"] += 1
            continue
        seen.add(source_key)
        (
            invoice,
            stock,
            description,
            quantity,
            invoice_date,
            price,
            customer,
            country,
        ) = values
        reasons: set[str] = set()
        invoice_id = _identifier(invoice, "invoice_id", reasons)
        stock_code = _identifier(stock, "product_id", reasons)
        if stock_code is not None and len(stock_code) > PRODUCT_ID_MAX_LENGTH:
            reasons.update({"invalid_product_id", "product_id_too_long"})
            stock_code = None
        description_text = _text(description, "description", reasons)
        signed_quantity = _quantity(quantity, reasons)
        parsed_date = _invoice_date(invoice_date, reasons)
        unit_price = _price(price, reasons)
        customer_id = _identifier(customer, "customer_id", reasons)
        country_text = _text(country, "country", reasons)
        customer_key = (
            hashlib.sha256(
                CUSTOMER_HASH_DOMAIN + customer_id.encode("utf-8")
            ).hexdigest()
            if customer_id is not None
            else None
        )
        if customer_key is not None:
            reasons.add("customer_pseudonymized")
        if invoice_id and invoice_id.startswith("c"):
            invoice_id = "C" + invoice_id[1:]
            reasons.add("invoice_prefix_normalized")
        is_cancellation = bool(invoice_id and invoice_id.startswith("C"))
        nonmerchandise = bool(stock_code and stock_code.upper() in NONMERCHANDISE_CODES)
        if nonmerchandise:
            reasons.add("nonmerchandise_code")
        sign_mismatch = bool(
            is_cancellation and signed_quantity is not None and signed_quantity > 0
        )
        if sign_mismatch:
            reasons.add("cancellation_sign_mismatch")
        for code in reasons:
            quality[code] += 1
        invalid = (
            invoice_id is None
            or stock_code is None
            or signed_quantity is None
            or parsed_date is None
            or unit_price is None
            or nonmerchandise
            or sign_mismatch
        )
        if invalid:
            disposition = "rejected"
            rejected += 1
        else:
            disposition = (
                "cancellation"
                if is_cancellation
                else "return" if signed_quantity < 0 else "purchase"
            )
            reasons.add(f"classified_{disposition}")
            partitions[disposition].append(
                {
                    "source_row": source_row,
                    "invoice_no": invoice_id,
                    "stock_code": stock_code,
                    "description": description_text,
                    "quantity": signed_quantity,
                    "invoice_date": parsed_date,
                    "unit_price": unit_price,
                    "customer_key": customer_key,
                    "country": country_text,
                }
            )
        reason_counts.update(reasons)
        audit_rows.append(
            {
                "source_row": source_row,
                "disposition": disposition,
                "reasons": "|".join(sorted(reasons)),
            }
        )
    cleaned = {
        name: _typed_frame(rows, TRANSACTION_DTYPES)
        for name, rows in partitions.items()
    }
    accepted = pd.concat(cleaned.values(), ignore_index=True)
    accepted_count = len(accepted)
    report: dict[str, Any] = {
        "cleaning_version": CLEANING_VERSION,
        "original_rows": len(frame),
        "cleaned_rows": accepted_count,
        "duplicate_rows": duplicates,
        "rejected_rows": rejected,
        "purchase_rows": len(cleaned["purchase"]),
        "cancellation_rows": len(cleaned["cancellation"]),
        "return_rows": len(cleaned["return"]),
        "missing_descriptions": quality["missing_description"],
        "missing_customer_ids": quality["missing_customer_id"],
        "missing_countries": quality["missing_country"],
        "invalid_prices": quality["invalid_price"],
        "invalid_quantities": quality["invalid_quantity"],
        "invalid_dates": quality["invalid_date"],
        "missing_invoice_ids": quality["missing_invoice_id"],
        "missing_product_ids": quality["missing_product_id"],
        "invalid_product_ids": quality["invalid_product_id"],
        "date_range": {
            "start": (
                accepted.invoice_date.min().isoformat() if accepted_count else None
            ),
            "end": accepted.invoice_date.max().isoformat() if accepted_count else None,
        },
        "unique_products": int(accepted.stock_code.nunique()),
        "unique_invoices": int(accepted.invoice_no.nunique()),
        "unique_customers": int(accepted.customer_key.nunique()),
        "unique_countries": int(accepted.country.nunique()),
        "countries": sorted(accepted.country.dropna().unique().tolist()),
        "reason_counts": dict(sorted(reason_counts.items())),
        "count_scopes": {
            "row_totals": "all source rows; dispositions are mutually exclusive",
            "quality_flags": "nonduplicate source rows before validation; flags overlap",
            "reason_counts": "audit rows containing the code; codes overlap",
            "entities_and_date_range": "accepted purchases, cancellations and returns",
        },
        "stages": [
            {
                "stage": "source_rows",
                "before": len(frame),
                "after": len(frame),
                "removed": 0,
            },
            {
                "stage": "exact_source_deduplication",
                "before": len(frame),
                "after": len(frame) - duplicates,
                "removed": duplicates,
            },
            {
                "stage": "validation_and_eligibility",
                "before": len(frame) - duplicates,
                "after": accepted_count,
                "removed": rejected,
            },
            {
                "stage": "classification",
                "before": accepted_count,
                "after": accepted_count,
                "removed": 0,
                "partitions": {
                    "purchases": len(cleaned["purchase"]),
                    "cancellations": len(cleaned["cancellation"]),
                    "returns": len(cleaned["return"]),
                },
            },
        ],
        "policies": {
            "deduplication": "exact typed source values before normalization; first retained",
            "product_identifiers": "normalized stock codes are limited to 128 Unicode characters; longer codes rejected",
            "dates": "naive London wall time; ISO or explicit DD/MM/YYYY; no timezone inference",
            "quantity": "signed int64; reject zero/fractional/nonfinite/out-of-range; no outlier cap",
            "price": "finite strictly positive float64 for every accepted movement",
            "classification": "C-prefix and negative=cancellation; other negative=return; positive=purchase; C-positive rejected",
            "optional_fields": "missing retained; invalid description/country/customer scalar nulled and flagged",
            "customers": "SHA256 with demandiq:uci-online-retail:customer:v1 domain; linkable sensitive pseudonyms",
            "nonmerchandise_codes": sorted(NONMERCHANDISE_CODES),
            "cancellation_matching": "no inference or matching to historical invoices",
        },
    }
    assert len(frame) == duplicates + rejected + accepted_count
    return CleanResult(
        purchases=cleaned["purchase"],
        cancellations=cleaned["cancellation"],
        returns=cleaned["return"],
        audit=_typed_frame(audit_rows, AUDIT_DTYPES),
        report=report,
    )
