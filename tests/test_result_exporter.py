"""Tests for isolated run directories and result exports."""

import json

import pandas as pd
import pytest

from src.result_exporter import (
    build_cohort_retention,
    build_country_summary,
    build_monthly_summary,
    build_product_summary,
    build_segment_summary,
    create_run_directory,
    export_tables,
    export_transaction_tables,
    prepare_rfm_export,
    validate_run_id,
    write_metadata,
)


def sample_transactions():
    return pd.DataFrame(
        {
            "InvoiceNo": ["A", "A", "B", "C", "D"],
            "StockCode": ["P1", "P2", "P1", "P1", "P2"],
            "Description": ["Widget", "Gadget", "Widget", "Widget", "Gadget"],
            "Quantity": [2, 1, 3, 1, 1],
            "InvoiceDate": pd.to_datetime(
                ["2024-01-05", "2024-01-05", "2024-01-20", "2024-02-10", "2024-02-12"]
            ),
            "UnitPrice": [10.0, 10.0, 10.0, 40.0, 50.0],
            "CustomerID": [1, 1, 2, 1, 3],
            "Country": ["UK", "UK", "UK", "UK", "France"],
            "TotalAmount": [20.0, 10.0, 30.0, 40.0, 50.0],
        }
    )


def sample_results():
    rfm = pd.DataFrame(
        {
            "CustomerID": [1, 2, 3],
            "Recency": [5, 20, 40],
            "Frequency": [8, 3, 1],
            "Monetary": [800.0, 150.0, 50.0],
            "R_Score": [5, 3, 1],
            "F_Score": [5, 3, 1],
            "M_Score": [5, 3, 1],
            "Segment": ["Champions", "Loyal Customers", "Lost"],
            "Cluster": [2, 1, 0],
            "KMeans_Label": ["Super VIPs", "Regular", "Inactive"],
        }
    )
    kmeans = pd.DataFrame(
        {"k": [2, 3], "inertia": [10.0, 6.0], "silhouette": [0.3, 0.4], "davies_bouldin": [1.2, 0.9]}
    )
    comparison = pd.DataFrame(
        {
            "algorithm": ["K-Means", "GMM"],
            "transform": ["log", "log"],
            "silhouette": [0.4, 0.2],
            "davies_bouldin": [0.9, 1.4],
            "hopkins": [0.95, 0.95],
            "bic": [None, 100.0],
            "aic": [None, 90.0],
        }
    )
    return rfm, kmeans, comparison


def test_run_directory_has_required_subdirectories(tmp_path):
    paths = create_run_directory(tmp_path, "test_run")
    assert paths.root == tmp_path.resolve() / "test_run"
    assert paths.tables.is_dir()
    assert paths.visualizations.is_dir()
    assert paths.metadata.is_dir()


def test_existing_run_directory_is_never_overwritten(tmp_path):
    create_run_directory(tmp_path, "same_run")
    marker = tmp_path / "same_run" / "marker.txt"
    marker.write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError):
        create_run_directory(tmp_path, "same_run")
    assert marker.read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize("run_id", ["../escape", "nested/run", "nested\\run", "..", " bad"])
def test_invalid_run_id_is_rejected(run_id):
    with pytest.raises(ValueError):
        validate_run_id(run_id)


def test_csv_and_json_exports_are_readable_and_complete(tmp_path):
    paths = create_run_directory(tmp_path, "readable")
    rfm, kmeans, comparison = sample_results()
    segment_summary = build_segment_summary(rfm)
    exported = export_tables(paths, rfm, segment_summary, kmeans, comparison)
    metadata_path = write_metadata(paths, {"run_id": paths.run_id, "output_files": []})

    assert len(exported) == 4
    rfm_read = pd.read_csv(paths.tables / "rfm_customers.csv")
    summary_read = pd.read_csv(paths.tables / "segment_summary.csv")
    pd.read_csv(paths.tables / "kmeans_evaluation.csv")
    pd.read_csv(paths.tables / "algorithm_comparison.csv")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    required = {
        "R_Score", "F_Score", "M_Score", "Segment", "Cluster",
        "KMeans_Label", "ClusterLabel",
    }
    assert required.issubset(rfm_read.columns)
    assert int(summary_read["CustomerCount"].sum()) == len(rfm_read)
    assert summary_read["MonetaryShare"].sum() == pytest.approx(1.0)
    assert metadata["run_id"] == "readable"


def test_prepare_rfm_export_does_not_mutate_input():
    rfm, _, _ = sample_results()
    original_columns = list(rfm.columns)
    exported = prepare_rfm_export(rfm)
    assert list(rfm.columns) == original_columns
    assert exported["ClusterLabel"].equals(exported["KMeans_Label"])


def test_transaction_summaries_reconcile_revenue_orders_and_customers():
    transactions = sample_transactions()
    monthly = build_monthly_summary(transactions)
    country = build_country_summary(transactions)
    product = build_product_summary(transactions)

    expected_revenue = transactions["TotalAmount"].sum()
    assert monthly["Revenue"].sum() == pytest.approx(expected_revenue)
    assert country["Revenue"].sum() == pytest.approx(expected_revenue)
    assert product["Revenue"].sum() == pytest.approx(expected_revenue)

    january = monthly.loc[monthly["Month"].eq("2024-01")].iloc[0]
    assert january["Revenue"] == pytest.approx(60.0)
    assert january["Orders"] == 2
    assert january["Customers"] == 2
    assert january["Quantity"] == 6
    assert january["AverageOrderValue"] == pytest.approx(30.0)

    widget = product.loc[
        product["StockCode"].eq("P1") & product["Description"].eq("Widget")
    ].iloc[0]
    assert widget["Revenue"] == pytest.approx(90.0)
    assert widget["Orders"] == 3
    assert widget["Customers"] == 2


def test_cohort_retention_uses_unique_customers_and_zero_based_periods():
    retention = build_cohort_retention(sample_transactions())

    january_zero = retention.loc[
        retention["CohortMonth"].eq("2024-01") & retention["Period"].eq(0)
    ].iloc[0]
    january_one = retention.loc[
        retention["CohortMonth"].eq("2024-01") & retention["Period"].eq(1)
    ].iloc[0]
    february_zero = retention.loc[
        retention["CohortMonth"].eq("2024-02") & retention["Period"].eq(0)
    ].iloc[0]

    assert january_zero["Customers"] == 2
    assert january_zero["CohortSize"] == 2
    assert january_zero["RetentionRate"] == pytest.approx(1.0)
    assert january_one["Customers"] == 1
    assert january_one["RetentionRate"] == pytest.approx(0.5)
    assert february_zero["Customers"] == 1
    assert february_zero["RetentionRate"] == pytest.approx(1.0)
    assert retention.loc[retention["Period"].eq(0), "RetentionRate"].eq(1.0).all()


def test_transaction_exports_are_readable_and_keep_input_snapshot(tmp_path):
    paths = create_run_directory(tmp_path, "transaction_exports")
    transactions = sample_transactions()
    exported = export_transaction_tables(paths, transactions)

    assert len(exported) == 5
    assert {path.name for path in exported} == {
        "transaction_clean.csv",
        "monthly_summary.csv",
        "country_summary.csv",
        "product_summary.csv",
        "cohort_retention.csv",
    }
    snapshot = pd.read_csv(paths.tables / "transaction_clean.csv")
    assert list(snapshot.columns) == list(transactions.columns)
    assert len(snapshot) == len(transactions)
    assert snapshot["TotalAmount"].sum() == pytest.approx(150.0)
