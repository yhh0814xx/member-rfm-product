"""Isolated run-directory creation and result export helpers."""

from __future__ import annotations

import hashlib
import json
import math
import re
import secrets
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import metadata as package_metadata
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
DEPENDENCY_NAMES = ("pandas", "numpy", "scikit-learn", "matplotlib", "seaborn")
TRANSACTION_COLUMNS = (
    "InvoiceNo",
    "StockCode",
    "Description",
    "Quantity",
    "InvoiceDate",
    "UnitPrice",
    "CustomerID",
    "Country",
    "TotalAmount",
)


@dataclass(frozen=True)
class RunPaths:
    """Filesystem locations for one immutable pipeline run."""

    run_id: str
    root: Path
    tables: Path
    visualizations: Path
    metadata: Path


def generate_run_id() -> str:
    """Generate a sortable UTC run identifier with collision resistance."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{timestamp}_{secrets.token_hex(3)}"


def validate_run_id(run_id: str) -> str:
    """Reject path traversal, separators, and ambiguous directory names."""
    if run_id in {".", ".."} or not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError(
            "run_id must be 1-128 characters, start with a letter or digit, "
            "and contain only letters, digits, '.', '_' or '-'."
        )
    return run_id


def create_run_directory(output_root: Path | str, run_id: str | None = None) -> RunPaths:
    """Create an isolated run tree, failing if the run directory exists."""
    selected_id = validate_run_id(run_id) if run_id is not None else generate_run_id()
    root = Path(output_root).expanduser().resolve() / selected_id
    root.mkdir(parents=True, exist_ok=False)
    tables = root / "tables"
    visualizations = root / "visualizations"
    metadata_dir = root / "metadata"
    tables.mkdir()
    visualizations.mkdir()
    metadata_dir.mkdir()
    return RunPaths(selected_id, root, tables, visualizations, metadata_dir)


def sha256_file(path: Path | str, chunk_size: int = 1024 * 1024) -> str:
    """Return the uppercase SHA-256 for a file."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def prepare_rfm_export(rfm: pd.DataFrame) -> pd.DataFrame:
    """Preserve analysis columns and expose a stable cluster label alias."""
    exported = rfm.copy()
    if "KMeans_Label" in exported.columns and "ClusterLabel" not in exported.columns:
        exported["ClusterLabel"] = exported["KMeans_Label"]
    return exported


def build_segment_summary(rfm: pd.DataFrame) -> pd.DataFrame:
    """Build an auditable segment summary whose shares sum to one."""
    summary = (
        rfm.groupby("Segment", as_index=False)
        .agg(
            CustomerCount=("CustomerID", "size"),
            MonetaryTotal=("Monetary", "sum"),
            AverageMonetary=("Monetary", "mean"),
        )
    )
    customer_total = int(summary["CustomerCount"].sum())
    monetary_total = float(summary["MonetaryTotal"].sum())
    summary["CustomerShare"] = (
        summary["CustomerCount"] / customer_total if customer_total else 0.0
    )
    summary["MonetaryShare"] = (
        summary["MonetaryTotal"] / monetary_total if monetary_total else 0.0
    )
    return summary.sort_values("MonetaryTotal", ascending=False).reset_index(drop=True)


def prepare_transaction_snapshot(transactions: pd.DataFrame) -> pd.DataFrame:
    """Return an unchanged copy of this run's already-cleaned input data."""
    missing = [column for column in TRANSACTION_COLUMNS if column not in transactions.columns]
    if missing:
        raise ValueError(
            "cleaned transaction input is missing required columns: "
            + ", ".join(missing)
        )
    snapshot = transactions.copy()
    snapshot["InvoiceDate"] = pd.to_datetime(snapshot["InvoiceDate"], errors="raise")
    return snapshot


def _add_month(transactions: pd.DataFrame) -> pd.DataFrame:
    prepared = prepare_transaction_snapshot(transactions)
    if prepared["InvoiceDate"].isna().any():
        raise ValueError("cleaned transaction input contains missing InvoiceDate values")
    prepared["Month"] = prepared["InvoiceDate"].dt.to_period("M").astype(str)
    return prepared


def _add_average_order_value(summary: pd.DataFrame) -> pd.DataFrame:
    summary["AverageOrderValue"] = summary["Revenue"].div(
        summary["Orders"].where(summary["Orders"].ne(0))
    ).fillna(0.0)
    return summary


def build_monthly_summary(transactions: pd.DataFrame) -> pd.DataFrame:
    """Aggregate real revenue, orders, customers and quantity by calendar month."""
    prepared = _add_month(transactions)
    summary = (
        prepared.groupby("Month", as_index=False, dropna=False)
        .agg(
            Revenue=("TotalAmount", "sum"),
            Orders=("InvoiceNo", "nunique"),
            Customers=("CustomerID", "nunique"),
            Quantity=("Quantity", "sum"),
        )
        .sort_values("Month")
        .reset_index(drop=True)
    )
    return _add_average_order_value(summary)


def build_country_summary(transactions: pd.DataFrame) -> pd.DataFrame:
    """Aggregate transaction facts by the source Country field."""
    prepared = prepare_transaction_snapshot(transactions)
    summary = (
        prepared.groupby("Country", as_index=False, dropna=False)
        .agg(
            Revenue=("TotalAmount", "sum"),
            Orders=("InvoiceNo", "nunique"),
            Customers=("CustomerID", "nunique"),
            Quantity=("Quantity", "sum"),
        )
        .sort_values("Revenue", ascending=False)
        .reset_index(drop=True)
    )
    return _add_average_order_value(summary)


def build_product_summary(transactions: pd.DataFrame) -> pd.DataFrame:
    """Aggregate products jointly by their real StockCode and Description."""
    prepared = prepare_transaction_snapshot(transactions)
    return (
        prepared.groupby(["StockCode", "Description"], as_index=False, dropna=False)
        .agg(
            Revenue=("TotalAmount", "sum"),
            Orders=("InvoiceNo", "nunique"),
            Customers=("CustomerID", "nunique"),
            Quantity=("Quantity", "sum"),
        )
        .sort_values("Revenue", ascending=False)
        .reset_index(drop=True)
    )


def build_cohort_retention(transactions: pd.DataFrame) -> pd.DataFrame:
    """Build long-form monthly retention using unique CustomerID counts."""
    prepared = prepare_transaction_snapshot(transactions).dropna(
        subset=["CustomerID", "InvoiceDate"]
    )
    purchase_month = prepared["InvoiceDate"].dt.to_period("M").dt.to_timestamp()
    prepared = prepared.assign(PurchaseMonth=purchase_month)
    prepared["CohortMonth"] = prepared.groupby("CustomerID")[
        "PurchaseMonth"
    ].transform("min")
    prepared["Period"] = (
        (prepared["PurchaseMonth"].dt.year - prepared["CohortMonth"].dt.year) * 12
        + prepared["PurchaseMonth"].dt.month
        - prepared["CohortMonth"].dt.month
    )

    retention = (
        prepared.groupby(["CohortMonth", "Period"], as_index=False)["CustomerID"]
        .nunique()
        .rename(columns={"CustomerID": "Customers"})
    )
    cohort_sizes = (
        retention.loc[retention["Period"].eq(0), ["CohortMonth", "Customers"]]
        .set_index("CohortMonth")["Customers"]
        .rename("CohortSize")
    )
    retention = retention.join(cohort_sizes, on="CohortMonth")
    retention["RetentionRate"] = retention["Customers"] / retention["CohortSize"]
    retention["CohortMonth"] = retention["CohortMonth"].dt.strftime("%Y-%m")
    return retention.sort_values(["CohortMonth", "Period"]).reset_index(drop=True)


def export_transaction_tables(
    paths: RunPaths, transactions: pd.DataFrame
) -> list[Path]:
    """Export the cleaned-input snapshot and four transaction-derived summaries."""
    snapshot = prepare_transaction_snapshot(transactions)
    monthly = build_monthly_summary(snapshot)
    country = build_country_summary(snapshot)
    product = build_product_summary(snapshot)
    cohort = build_cohort_retention(snapshot)

    source_revenue = float(snapshot["TotalAmount"].sum())
    for name, summary in (
        ("monthly_summary.csv", monthly),
        ("country_summary.csv", country),
        ("product_summary.csv", product),
    ):
        if not math.isclose(
            float(summary["Revenue"].sum()), source_revenue, rel_tol=1e-9, abs_tol=0.01
        ):
            raise ValueError(f"{name} revenue does not reconcile to transaction input")

    outputs = [
        (paths.tables / "transaction_clean.csv", snapshot),
        (paths.tables / "monthly_summary.csv", monthly),
        (paths.tables / "country_summary.csv", country),
        (paths.tables / "product_summary.csv", product),
        (paths.tables / "cohort_retention.csv", cohort),
    ]
    for output_path, frame in outputs:
        frame.to_csv(output_path, index=False, encoding="utf-8")
    return [path for path, _ in outputs]


def export_tables(
    paths: RunPaths,
    rfm: pd.DataFrame,
    segment_summary: pd.DataFrame,
    kmeans_evaluation: pd.DataFrame,
    algorithm_comparison: pd.DataFrame,
) -> list[Path]:
    """Export the four required CSV tables into the run's tables directory."""
    outputs = [
        (paths.tables / "rfm_customers.csv", prepare_rfm_export(rfm)),
        (paths.tables / "segment_summary.csv", segment_summary),
        (paths.tables / "kmeans_evaluation.csv", kmeans_evaluation),
        (paths.tables / "algorithm_comparison.csv", algorithm_comparison),
    ]
    for output_path, frame in outputs:
        frame.to_csv(output_path, index=False, encoding="utf-8")
    return [path for path, _ in outputs]


def runtime_versions() -> dict[str, Any]:
    """Return Python and major dependency versions."""
    dependencies = {}
    for name in DEPENDENCY_NAMES:
        try:
            dependencies[name] = package_metadata.version(name)
        except package_metadata.PackageNotFoundError:
            dependencies[name] = None
    return {
        "python": sys.version.split()[0],
        "python_full": sys.version,
        "dependencies": dependencies,
    }


def relative_manifest(run_root: Path, files: Iterable[Path]) -> list[str]:
    """Return POSIX-style paths relative to a run root."""
    return [Path(path).resolve().relative_to(run_root.resolve()).as_posix() for path in files]


def write_metadata(paths: RunPaths, payload: dict[str, Any]) -> Path:
    """Write the required JSON metadata file without replacing an existing file."""
    output_path = paths.metadata / "run_metadata.json"
    with output_path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return output_path
