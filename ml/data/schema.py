"""Structural contract for the eight official UCI Online Retail source fields."""

from typing import Final

import pandas as pd

SOURCE_COLUMNS: Final[tuple[str, ...]] = (
    "InvoiceNo",
    "StockCode",
    "Description",
    "Quantity",
    "InvoiceDate",
    "UnitPrice",
    "CustomerID",
    "Country",
)


class SchemaError(ValueError):
    """The source cannot be interpreted as the specified transaction table."""


SchemaValidationError = SchemaError


def validate_input(frame: pd.DataFrame) -> None:
    """Require the exact named fields, permitting any order and invalid row values.

    Scalar errors belong in the row audit rather than failing the whole import.
    Error messages deliberately exclude source cell values and customer information.
    """
    if not isinstance(frame, pd.DataFrame):
        raise SchemaValidationError(
            "Expected a pandas DataFrame with eight source fields"
        )
    if isinstance(frame.columns, pd.MultiIndex):
        raise SchemaValidationError("Source columns must be a flat, unique index")
    if frame.columns.has_duplicates:
        raise SchemaValidationError("Duplicate source column names are not supported")
    missing = [name for name in SOURCE_COLUMNS if name not in frame.columns]
    unexpected = sum(name not in SOURCE_COLUMNS for name in frame.columns)
    if missing or unexpected:
        raise SchemaValidationError(
            f"Source schema mismatch: missing required fields {missing}; "
            f"unexpected field count {unexpected}"
        )
