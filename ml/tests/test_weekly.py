"""Synthetic arithmetic, temporal-boundary and leakage checks for weekly data."""

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from ml.data.cleaning import INT64_MAX, INT64_MIN, clean_transactions
from ml.data.weekly import (
    SELECTION_DTYPES,
    WEEKLY_DTYPES,
    WeeklyDataError,
    aggregate_weekly,
    select_top_products,
)

SOURCE_DTYPES = {
    "source_row": "int64",
    "invoice_no": "string",
    "stock_code": "string",
    "quantity": "int64",
    "invoice_date": "datetime64[ns]",
    "unit_price": "float64",
    "customer_key": "string",
}


def movement(row_id, **changes):
    return {
        "source_row": row_id,
        "invoice_no": f"SYNTH-{row_id}",
        "stock_code": "A",
        "quantity": 2,
        "invoice_date": pd.Timestamp("2011-01-03 12:00"),
        "unit_price": 3.0,
        "customer_key": "synthetic-pseudonym-a",
    } | changes


def transactions(*rows):
    if not rows:
        return pd.DataFrame(
            {column: pd.Series(dtype=dtype) for column, dtype in SOURCE_DTYPES.items()}
        )
    return pd.DataFrame(rows)


def aggregate(purchases=None, cancellations=None, returns=None, **kwargs):
    return aggregate_weekly(
        transactions() if purchases is None else purchases,
        transactions() if cancellations is None else cancellations,
        transactions() if returns is None else returns,
        start_week=kwargs.pop("start_week", "2011-01-03"),
        end_week=kwargs.pop("end_week", "2011-01-17"),
        **kwargs,
    )


def panel_for(values, start="2011-01-03"):
    rows = [
        {"stock_code": code, "week": week, "gross_units": quantity}
        for code, quantities in values.items()
        for week, quantity in zip(
            pd.date_range(start, periods=len(quantities), freq="W-MON"),
            quantities,
            strict=True,
        )
    ]
    return pd.DataFrame(rows).astype(
        {"stock_code": "string", "week": "datetime64[ns]", "gross_units": "int64"}
    )


def test_hand_calculated_weekly_movements_purchase_metrics_and_missing_weeks():
    result = aggregate(
        purchases=transactions(
            movement(1, quantity=2, unit_price=3.0),
            movement(2, quantity=3, unit_price=4.0),
            movement(3, quantity=1, unit_price=6.0, customer_key=None),
            movement(4, stock_code="B", invoice_date=pd.Timestamp("2011-01-17")),
        ),
        cancellations=transactions(movement(5, invoice_no="C-SYNTH-5", quantity=-1)),
        returns=transactions(movement(6, quantity=-2)),
    )
    assert result.stock_code.tolist() == ["A"] * 3 + ["B"] * 3
    assert (
        result.week.tolist()
        == list(pd.date_range("2011-01-03", periods=3, freq="W-MON")) * 2
    )
    first = result.iloc[0]
    assert first.gross_units == 6
    assert first.returned_units == 2
    assert first.cancellation_units == 1
    assert first.net_units == 3
    assert first.revenue == 24.0
    assert first.transactions == 3
    assert first.unique_customers == 1
    assert first.average_price == 4.0
    zero = result.iloc[1]
    assert zero.gross_units == zero.net_units == zero.revenue == 0
    assert zero.transactions == zero.unique_customers == 0
    assert np.isnan(zero.average_price)
    assert result.dtypes.astype(str).to_dict() == WEEKLY_DTYPES
    assert "customer_key" not in result.columns
    assert "invoice_no" not in result.columns
    assert "source_row" not in result.columns


def test_entire_end_week_is_included_and_adjacent_weeks_excluded():
    source = transactions(
        movement(1, invoice_date=pd.Timestamp("2011-01-02 23:59:59.999999999")),
        movement(2, invoice_date=pd.Timestamp("2011-01-03 00:00")),
        movement(3, invoice_date=pd.Timestamp("2011-01-23 23:59:59.999999999")),
        movement(4, invoice_date=pd.Timestamp("2011-01-24 00:00")),
    )
    result = aggregate(source)
    assert result.gross_units.tolist() == [2, 0, 2]


def test_default_union_uses_only_products_observed_inside_window_and_all_classes():
    result = aggregate(
        purchases=transactions(
            movement(1, stock_code="OUT", invoice_date=pd.Timestamp("2010-12-27"))
        ),
        cancellations=transactions(
            movement(2, invoice_no="C-SYNTH-2", stock_code="CANCEL", quantity=-3)
        ),
        returns=transactions(movement(3, stock_code="RETURN", quantity=-1)),
    )
    assert result.stock_code.unique().tolist() == ["CANCEL", "RETURN"]
    assert result.gross_units.eq(0).all()
    assert result.average_price.isna().all()
    assert result.loc[result.stock_code.eq("CANCEL"), "net_units"].tolist() == [
        -3,
        0,
        0,
    ]


def test_explicit_absent_products_have_zero_rows_in_sorted_complete_grid():
    result = aggregate(products=["Z", "A"])
    assert result.stock_code.tolist() == ["A"] * 3 + ["Z"] * 3
    assert result.gross_units.eq(0).all()
    assert result.revenue.eq(0).all()
    assert result.average_price.isna().all()


def test_empty_default_union_is_typed_empty():
    result = aggregate()
    assert result.empty
    assert result.dtypes.astype(str).to_dict() == WEEKLY_DTYPES


@pytest.mark.parametrize(
    "products",
    [[], ["A", "A"], [""], [" "], [None], [1], "ABC", ["A" * 129], [" A"], 1],
)
def test_invalid_product_configuration_rejected(products):
    with pytest.raises(WeeklyDataError, match="products"):
        aggregate(products=products)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("start_week", "2011-01-04"),
        ("start_week", "2011-01-03 00:01"),
        ("start_week", "2011-01-03 00:00:00.000000001"),
        ("start_week", "03/01/2011"),
        ("start_week", None),
        ("end_week", pd.Timestamp("2011-01-17", tz="UTC")),
        ("end_week", "2011-01-17T00:00Z"),
        ("end_week", True),
        ("end_week", pd.NaT),
        ("end_week", "9999-01-04"),
        ("end_week", "2262-04-07"),
    ],
)
def test_invalid_week_boundaries_rejected(name, value):
    with pytest.raises(WeeklyDataError):
        aggregate(**{name: value})


def test_start_after_end_rejected():
    with pytest.raises(WeeklyDataError, match="after"):
        aggregate(start_week="2011-01-24")


@pytest.mark.parametrize("partition", ["purchases", "cancellations", "returns"])
def test_missing_columns_rejected_in_every_partition(partition):
    with pytest.raises(WeeklyDataError, match="missing required columns"):
        aggregate(**{partition: transactions().drop(columns="quantity")})


def test_unsupported_frame_and_duplicate_columns_rejected():
    with pytest.raises(WeeklyDataError, match="DataFrame"):
        aggregate(purchases=[])
    source = transactions(movement(1))
    source.columns = ["source_row"] * len(source.columns)
    with pytest.raises(WeeklyDataError, match="unique flat"):
        aggregate(source)


def test_duplicate_source_ids_rejected_within_and_across_partitions():
    with pytest.raises(WeeklyDataError, match="duplicate source_row"):
        aggregate(transactions(movement(1), movement(1)))
    with pytest.raises(WeeklyDataError, match="overlap"):
        aggregate(
            transactions(movement(1)),
            returns=transactions(movement(1, quantity=-2)),
        )


@pytest.mark.parametrize("quantity", [0, -1, 1.0, True, None, "2", 2**63])
def test_invalid_purchase_quantities_rejected(quantity):
    with pytest.raises(WeeklyDataError):
        aggregate(transactions(movement(1, quantity=quantity)))


@pytest.mark.parametrize("quantity", [0, 1, INT64_MIN])
@pytest.mark.parametrize("partition", ["returns", "cancellations"])
def test_negative_partition_sign_and_absolute_overflow_rejected(quantity, partition):
    prefix = "C-SYNTH-1" if partition == "cancellations" else "SYNTH-1"
    with pytest.raises(WeeklyDataError):
        aggregate(
            **{
                partition: transactions(
                    movement(1, invoice_no=prefix, quantity=quantity)
                )
            }
        )


@pytest.mark.parametrize("partition", ["purchases", "returns", "cancellations"])
def test_cancellation_prefix_classification_must_match_partition(partition):
    quantity = 1 if partition == "purchases" else -1
    invoice = "SYNTH-1" if partition == "cancellations" else "C-SYNTH-1"
    with pytest.raises(WeeklyDataError, match="C-prefixed"):
        aggregate(
            **{
                partition: transactions(
                    movement(1, invoice_no=invoice, quantity=quantity)
                )
            }
        )


@pytest.mark.parametrize("price", [0, -1, np.nan, np.inf, True, None, "3.0", 10**400])
def test_invalid_prices_rejected(price):
    source = transactions(movement(1))
    source["unit_price"] = pd.Series([price], dtype=object)
    with pytest.raises(WeeklyDataError, match="price"):
        aggregate(source)


@pytest.mark.parametrize(
    "value", [pd.NaT, "2011-01-03", datetime(2011, 1, 3, tzinfo=UTC)]
)
def test_invalid_source_dates_are_not_guessed(value):
    with pytest.raises(WeeklyDataError, match="datetime"):
        aggregate(transactions(movement(1, invoice_date=value)))


def test_invalid_stock_invoice_customer_or_source_row_invariants_rejected():
    for changes in (
        {"stock_code": None},
        {"stock_code": " A"},
        {"invoice_no": None},
        {"invoice_no": " SYNTH-1 "},
        {"customer_key": True},
        {"source_row": 0},
    ):
        with pytest.raises(WeeklyDataError):
            aggregate(transactions(movement(1, **changes)))


def test_unit_sums_and_signed_net_overflow_raise_instead_of_wrapping():
    with pytest.raises(WeeklyDataError, match="aggregation range"):
        aggregate(
            transactions(movement(1, quantity=INT64_MAX), movement(2, quantity=1))
        )
    with pytest.raises(WeeklyDataError, match="net_units"):
        aggregate(
            cancellations=transactions(
                movement(1, invoice_no="C-SYNTH-1", quantity=-INT64_MAX)
            ),
            returns=transactions(movement(2, quantity=-INT64_MAX)),
        )


def test_int64_maximum_remains_exact_despite_inserted_zero_weeks():
    result = aggregate(transactions(movement(1, quantity=INT64_MAX, unit_price=1.0)))
    assert result.gross_units.tolist() == [INT64_MAX, 0, 0]
    assert result.net_units.tolist() == [INT64_MAX, 0, 0]


def test_signed_net_minimum_is_valid_when_separate_negative_classes_combine():
    result = aggregate(
        cancellations=transactions(movement(1, invoice_no="C-SYNTH-1", quantity=-1)),
        returns=transactions(movement(2, quantity=-INT64_MAX)),
    )
    assert result.net_units.tolist() == [INT64_MIN, 0, 0]


def test_individual_and_aggregate_revenue_overflow_rejected():
    maximum = np.finfo("float64").max
    with pytest.raises(WeeklyDataError, match="revenue"):
        aggregate(transactions(movement(1, quantity=2, unit_price=maximum)))
    with pytest.raises(WeeklyDataError, match="revenue"):
        aggregate(
            transactions(
                movement(1, quantity=1, unit_price=maximum),
                movement(2, quantity=1, unit_price=maximum),
            )
        )


def test_repeated_normalized_values_with_distinct_source_rows_are_not_deduplicated():
    result = aggregate(transactions(movement(1), movement(2)))
    assert result.iloc[0].gross_units == 4
    assert result.iloc[0].transactions == 2
    assert result.iloc[0].unique_customers == 1


def test_input_order_does_not_affect_output_or_modify_sources():
    source = transactions(movement(1), movement(2, stock_code="B"), movement(3))
    original = source.copy(deep=True)
    first = aggregate(source)
    second = aggregate(source.iloc[::-1])
    assert_frame_equal(first, second)
    assert_frame_equal(source, original)


def test_cleaning_to_weekly_vertical_interface():
    source = pd.DataFrame(
        [
            {
                "InvoiceNo": "SYNTH-1",
                "StockCode": "SYNTH-A",
                "Description": None,
                "Quantity": 2,
                "InvoiceDate": datetime(2011, 1, 3),
                "UnitPrice": 3.0,
                "CustomerID": None,
                "Country": None,
            }
        ]
    )
    cleaned = clean_transactions(source)
    result = aggregate(cleaned.purchases, cleaned.cancellations, cleaned.returns)
    assert result.iloc[0].gross_units == 2
    assert result.iloc[0].unique_customers == 0


def test_selection_training_only_future_volume_and_new_products_cannot_change_rank():
    source = panel_for({"A": [2] * 12 + [1] * 3, "B": [1] * 12 + [1] * 3})
    expected = select_top_products(source, train_end="2011-03-21", top_n=1)
    changed = source.copy()
    changed.loc[
        (changed.stock_code == "B") & (changed.week > "2011-03-21"), "gross_units"
    ] = 1_000_000
    future = panel_for({"FUTURE": [1_000_000] * 3}, start="2011-03-28")
    changed = pd.concat([changed, future], ignore_index=True)
    actual = select_top_products(changed, train_end="2011-03-21", top_n=1)
    assert_frame_equal(actual, expected)
    assert actual.to_dict("records") == [
        {"stock_code": "A", "training_units": 24, "active_training_weeks": 12}
    ]


def test_selection_zero_history_weeks_count_but_nonpositive_volume_is_ineligible():
    source = panel_for({"A": [0] * 11 + [5], "B": [0] * 12, "C": [1] * 12})
    result = select_top_products(source, train_end="2011-03-21")
    assert result.stock_code.tolist() == ["C", "A"]
    assert result.active_training_weeks.tolist() == [12, 1]
    assert result.training_units.tolist() == [12, 5]
    assert result.dtypes.astype(str).to_dict() == SELECTION_DTYPES


def test_selection_tie_breaking_sort_and_configurable_limits():
    source = panel_for({"Z": [1] * 12, "B": [1] * 12, "A": [1] * 12})
    result = select_top_products(source.iloc[::-1], train_end="2011-03-21", top_n=2)
    assert result.stock_code.tolist() == ["A", "B"]


def test_selection_requires_minimum_continuous_observation_count():
    source = panel_for({"A": [5] * 11})
    assert select_top_products(source, train_end="2011-03-14").empty
    assert select_top_products(
        source, train_end="2011-03-14", min_history_weeks=11
    ).stock_code.tolist() == ["A"]


def test_selection_rejects_duplicate_keys_and_missing_training_weeks():
    source = panel_for({"A": [1] * 12})
    with pytest.raises(WeeklyDataError, match="duplicate"):
        select_top_products(
            pd.concat([source, source.iloc[:1]]), train_end="2011-03-21"
        )
    with pytest.raises(WeeklyDataError, match="missing product-week"):
        select_top_products(source.drop(index=5), train_end="2011-03-21")
    with pytest.raises(WeeklyDataError, match="missing product-week"):
        select_top_products(source, train_end="2011-03-28")


@pytest.mark.parametrize("field", ["top_n", "min_history_weeks"])
@pytest.mark.parametrize("value", [0, -1, 1.5, True, "50"])
def test_selection_invalid_configuration_rejected(field, value):
    with pytest.raises(WeeklyDataError, match=field):
        select_top_products(
            panel_for({"A": [1] * 12}), train_end="2011-03-21", **{field: value}
        )


def test_selection_empty_no_training_and_no_positive_products_are_typed_empty():
    source = panel_for({"A": [0] * 12})
    for data, train_end in (
        (source.iloc[:0], "2011-03-21"),
        (source, "2010-12-27"),
        (source, "2011-03-21"),
    ):
        result = select_top_products(data, train_end=train_end)
        assert result.empty
        assert result.dtypes.astype(str).to_dict() == SELECTION_DTYPES


def test_selection_rejects_training_total_overflow_and_negative_volume():
    source = panel_for({"A": [INT64_MAX] + [1] * 11})
    with pytest.raises(WeeklyDataError, match="training_units"):
        select_top_products(source, train_end="2011-03-21")
    source.loc[0, "gross_units"] = -1
    with pytest.raises(WeeklyDataError, match="gross_units"):
        select_top_products(source, train_end="2011-03-21")


def test_selection_int64_maximum_total_is_exact():
    source = panel_for({"A": [INT64_MAX] + [0] * 11})
    result = select_top_products(source, train_end="2011-03-21")
    assert result.training_units.tolist() == [INT64_MAX]
    assert result.active_training_weeks.tolist() == [1]


def test_selection_validates_week_labels_and_source_schema():
    source = panel_for({"A": [1] * 12})
    with pytest.raises(WeeklyDataError, match="Monday"):
        select_top_products(
            source.assign(week=source.week + pd.Timedelta(days=1)),
            train_end="2011-03-21",
        )
    with pytest.raises(WeeklyDataError, match="missing required columns"):
        select_top_products(source.drop(columns="gross_units"), train_end="2011-03-21")
