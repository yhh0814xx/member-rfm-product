"""Tests for the unified display-only global filter pipeline."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pandas as pd

from app.dashboard_data import dataframe_to_csv_bytes, load_run, load_transaction_tables
from app.global_filters import (
    EMPTY_FILTER_MESSAGE,
    GlobalFilterState,
    apply_global_filters,
    normalize_customer_id,
)
from app.recommendations_view import prepare_view_result
from tests.test_dashboard_data import make_run


def load_bundles(tmp_path):
    run_dir = make_run(tmp_path, "global_filters")
    return load_run(run_dir), load_transaction_tables(run_dir)


def apply(tmp_path, **kwargs):
    bundle, transactions = load_bundles(tmp_path)
    state = GlobalFilterState(**kwargs)
    return bundle, apply_global_filters(bundle, state, transactions)


def test_country_filter_updates_transactions_customers_and_summaries(tmp_path):
    _, result = apply(tmp_path, countries=("France",))
    assert result.filtered_transactions["InvoiceNo"].tolist() == ["I2"]
    assert result.filtered_rfm_customers["CustomerID"].tolist() == ["1002.0"]
    assert result.filtered_country_summary["Country"].tolist() == ["France"]
    assert result.filtered_monthly_summary["Customers"].sum() == 1
    assert "国家：France" in result.active_filter_summary


def test_date_filter_updates_all_transaction_derived_results(tmp_path):
    _, result = apply(
        tmp_path,
        date_range=(pd.Timestamp("2024-02-01"), pd.Timestamp("2024-02-29")),
    )
    assert result.filtered_transactions["InvoiceNo"].tolist() == ["I3"]
    assert result.filtered_rfm_customers["CustomerID"].tolist() == ["1001.0"]
    assert result.filtered_monthly_summary["Month"].tolist() == ["2024-02"]
    assert result.filtered_cohort["CohortMonth"].unique().tolist() == ["2024-02"]


def test_product_filter_keeps_product_transactions_and_buyers(tmp_path):
    _, result = apply(tmp_path, products=("P1 | Widget",))
    assert result.filtered_transactions["InvoiceNo"].tolist() == ["I1", "I3"]
    assert result.filtered_rfm_customers["CustomerID"].tolist() == ["1001.0"]
    assert result.filtered_product_summary["StockCode"].tolist() == ["P1"]


def test_segment_filter_flows_back_to_transactions(tmp_path):
    _, result = apply(tmp_path, segments=("Champions",))
    assert result.filtered_rfm_customers["Segment"].tolist() == ["Champions"]
    assert result.filtered_transactions["InvoiceNo"].tolist() == ["I1", "I3"]
    assert result.filtered_segment_summary["CustomerCount"].tolist() == [1]


def test_customer_id_filter_affects_all_related_results(tmp_path):
    _, result = apply(tmp_path, customer_query="1002")
    assert result.filtered_rfm_customers["CustomerID"].tolist() == ["1002.0"]
    assert result.filtered_transactions["InvoiceNo"].tolist() == ["I2"]
    assert result.filtered_monthly_summary["Customers"].sum() == 1


def test_multiple_filter_dimensions_use_and_logic(tmp_path):
    _, result = apply(
        tmp_path,
        countries=("France",),
        products=("P2 | Gadget",),
        transaction_query="I2",
        segments=("At Risk",),
        customer_query="1002",
    )
    assert result.filtered_transactions["InvoiceNo"].tolist() == ["I2"]
    assert result.filtered_rfm_customers["Segment"].tolist() == ["At Risk"]


def test_clearing_filters_restores_complete_linked_run_scope(tmp_path):
    bundle, transactions = load_bundles(tmp_path)
    filtered = apply_global_filters(
        bundle, GlobalFilterState(countries=("France",)), transactions
    )
    cleared = apply_global_filters(bundle, GlobalFilterState(), transactions)
    assert len(filtered.filtered_transactions) == 1
    assert len(cleared.filtered_transactions) == 3
    assert len(cleared.filtered_rfm_customers) == len(bundle.rfm_customers) == 2


def test_empty_filter_result_is_safe_and_has_stable_schemas(tmp_path):
    _, result = apply(
        tmp_path,
        countries=("France",),
        segments=("Champions",),
    )
    assert result.filtered_transactions.empty
    assert result.filtered_rfm_customers.empty
    assert result.filtered_segment_summary.empty
    assert result.filtered_cohort.empty
    assert EMPTY_FILTER_MESSAGE


def test_global_filter_preserves_exported_rfm_and_cluster_values(tmp_path):
    bundle, result = apply(tmp_path, countries=("France",))
    columns = [
        "Recency",
        "Frequency",
        "Monetary",
        "Segment",
        "Cluster",
        "KMeans_Label",
        "ClusterLabel",
    ]
    expected = bundle.rfm_customers.loc[
        bundle.rfm_customers["CustomerID"].eq("1002.0"), columns
    ].reset_index(drop=True)
    actual = result.filtered_rfm_customers[columns].reset_index(drop=True)
    pd.testing.assert_frame_equal(actual, expected)


def test_recommendations_use_globally_filtered_customers(tmp_path):
    bundle, result = apply(tmp_path, countries=("France",))
    recommendations = prepare_view_result(
        bundle,
        rfm_customers=result.filtered_rfm_customers,
        segment_summary=result.filtered_segment_summary,
    )
    counts = recommendations.recommendations.set_index("Segment")["CustomerCount"]
    assert counts["At Risk"] == 1
    assert counts["Champions"] == 0
    assert recommendations.customers["CustomerID"].tolist() == ["1002"]


def test_filtered_download_matches_displayed_rows(tmp_path):
    _, result = apply(tmp_path, segments=("Champions",))
    downloaded = pd.read_csv(BytesIO(dataframe_to_csv_bytes(result.filtered_transactions)))
    assert downloaded["InvoiceNo"].tolist() == ["I1", "I3"]
    assert len(downloaded) == len(result.filtered_transactions)


def test_filter_module_does_not_invoke_analysis_pipeline():
    source = (Path(__file__).resolve().parents[1] / "app" / "global_filters.py").read_text(
        encoding="utf-8"
    )
    assert "RFMPipeline" not in source
    assert "run_pipeline" not in source


def test_customer_id_normalization_accepts_string_integer_and_float():
    assert normalize_customer_id("1001.0") == "1001"
    assert normalize_customer_id(1001) == "1001"
    assert normalize_customer_id(1001.0) == "1001"
    assert normalize_customer_id("MEMBER-1") == "MEMBER-1"
