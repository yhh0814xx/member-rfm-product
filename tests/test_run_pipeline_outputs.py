"""Integration test for isolated full-pipeline output."""

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

import run_pipeline


EXPECTED_IMAGES = {
    "1_rfm_segment_overview.png",
    "2_rfm_executive_summary.png",
    "3_rfm_3d_scatter.png",
    "4_rfm_action_cards.png",
    "5_kmeans_elbow_method.png",
    "6_kmeans_final_comparison.png",
    "7_algorithm_comparison.png",
}


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_full_pipeline_writes_only_to_isolated_run(tmp_path):
    project_root = Path(run_pipeline.__file__).resolve().parent
    input_path = project_root / "data" / "online_retail_clean.csv"
    example_dir = project_root / "visualizations"
    hashes_before = {path.name: file_hash(path) for path in example_dir.glob("*.png")}

    paths = run_pipeline.main(
        [
            "--input", str(input_path),
            "--output-root", str(tmp_path),
            "--run-id", "integration_test",
        ]
    )

    assert paths.root == tmp_path.resolve() / "integration_test"
    assert {path.name for path in paths.visualizations.glob("*.png")} == EXPECTED_IMAGES
    assert {path.name for path in paths.tables.glob("*.csv")} == {
        "rfm_customers.csv",
        "segment_summary.csv",
        "kmeans_evaluation.csv",
        "algorithm_comparison.csv",
    }
    metadata_path = paths.metadata / "run_metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    rfm = pd.read_csv(paths.tables / "rfm_customers.csv")
    summary = pd.read_csv(paths.tables / "segment_summary.csv")

    assert metadata["run_id"] == "integration_test"
    assert metadata["input"]["sha256"]
    assert metadata["input"]["rows"] == 388724
    assert metadata["input"]["customers"] == 4290
    assert metadata["input"]["orders"] == 18018
    assert int(summary["CustomerCount"].sum()) == len(rfm) == 4290
    assert summary["MonetaryShare"].sum() == pytest.approx(1.0)
    assert {path.name: file_hash(path) for path in example_dir.glob("*.png")} == hashes_before
