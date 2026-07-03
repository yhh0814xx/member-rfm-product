"""Tests for dashboard loading without network or reference-project access."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pandas as pd
import pytest

from app.dashboard_data import (
    IMAGE_FILES,
    RunDataError,
    compute_kpis,
    discover_runs,
    filter_customers,
    load_run,
)


ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUB"
    "AScY42YAAAAASUVORK5CYII="
)


def make_run(root: Path, run_id: str = "test_run") -> Path:
    run_dir = root / run_id
    tables = run_dir / "tables"
    visuals = run_dir / "visualizations"
    metadata = run_dir / "metadata"
    tables.mkdir(parents=True)
    visuals.mkdir()
    metadata.mkdir()

    pd.DataFrame(
        [
            {
                "CustomerID": "1001.0",
                "Recency": 5,
                "Frequency": 4,
                "Monetary": 120.5,
                "R_Score": 5,
                "F_Score": 4,
                "M_Score": 3,
                "Segment": "Champions",
                "Cluster": 1,
                "KMeans_Label": "VIP",
                "ClusterLabel": "VIP",
            },
            {
                "CustomerID": "1002.0",
                "Recency": 50,
                "Frequency": 2,
                "Monetary": 79.5,
                "R_Score": 2,
                "F_Score": 2,
                "M_Score": 2,
                "Segment": "At Risk",
                "Cluster": 0,
                "KMeans_Label": "Regular",
                "ClusterLabel": "Regular",
            },
        ]
    ).to_csv(tables / "rfm_customers.csv", index=False)
    pd.DataFrame(
        [
            {
                "Segment": "Champions",
                "CustomerCount": 1,
                "MonetaryTotal": 120.5,
                "AverageMonetary": 120.5,
                "CustomerShare": 0.5,
                "MonetaryShare": 0.6025,
            },
            {
                "Segment": "At Risk",
                "CustomerCount": 1,
                "MonetaryTotal": 79.5,
                "AverageMonetary": 79.5,
                "CustomerShare": 0.5,
                "MonetaryShare": 0.3975,
            },
        ]
    ).to_csv(tables / "segment_summary.csv", index=False)
    pd.DataFrame(
        [
            {"k": 2, "inertia": 10.0, "silhouette": 0.3, "davies_bouldin": 1.1},
            {"k": 3, "inertia": 7.0, "silhouette": 0.4, "davies_bouldin": 0.9},
        ]
    ).to_csv(tables / "kmeans_evaluation.csv", index=False)
    pd.DataFrame(
        [
            {
                "algorithm": "K-Means",
                "transform": "log",
                "silhouette": 0.4,
                "davies_bouldin": 0.9,
                "hopkins": 0.8,
                "bic": None,
                "aic": None,
            }
        ]
    ).to_csv(tables / "algorithm_comparison.csv", index=False)
    (metadata / "run_metadata.json").write_text(
        json.dumps({"run_id": run_id, "completed_at_utc": "2026-07-03T00:00:00Z"}),
        encoding="utf-8",
    )
    for filename in IMAGE_FILES:
        (visuals / filename).write_bytes(ONE_PIXEL_PNG)
    return run_dir


def test_discover_runs_returns_latest_first(tmp_path):
    older = make_run(tmp_path, "older")
    newer = make_run(tmp_path, "newer")
    older.touch()
    newer.touch()
    older_time = 1_700_000_000
    newer_time = older_time + 60
    import os

    os.utime(older, (older_time, older_time))
    os.utime(newer, (newer_time, newer_time))
    assert [path.name for path in discover_runs(tmp_path)] == ["newer", "older"]


def test_load_run_kpis_and_filters(tmp_path):
    bundle = load_run(make_run(tmp_path))
    assert bundle.run_id == "test_run"
    assert compute_kpis(bundle.rfm_customers) == {
        "customers": 2,
        "monetary": 200.0,
        "average_frequency": 3.0,
        "segments": 2,
    }
    assert filter_customers(bundle.rfm_customers, ["Champions"], "1001")[
        "CustomerID"
    ].tolist() == ["1001.0"]


def test_load_run_reports_missing_file_in_chinese(tmp_path):
    run_dir = make_run(tmp_path)
    (run_dir / "tables" / "segment_summary.csv").unlink()
    with pytest.raises(RunDataError, match="运行结果缺少文件"):
        load_run(run_dir)


def test_load_run_reports_bad_column_in_chinese(tmp_path):
    run_dir = make_run(tmp_path)
    path = run_dir / "tables" / "rfm_customers.csv"
    pd.read_csv(path).drop(columns="Monetary").to_csv(path, index=False)
    with pytest.raises(RunDataError, match="缺少字段：Monetary"):
        load_run(run_dir)
