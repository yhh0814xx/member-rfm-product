"""Load and validate immutable pipeline outputs for the dashboard."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


TABLE_SPECS: dict[str, tuple[str, ...]] = {
    "rfm_customers.csv": (
        "CustomerID",
        "Recency",
        "Frequency",
        "Monetary",
        "R_Score",
        "F_Score",
        "M_Score",
        "Segment",
        "Cluster",
        "KMeans_Label",
        "ClusterLabel",
    ),
    "segment_summary.csv": (
        "Segment",
        "CustomerCount",
        "MonetaryTotal",
        "AverageMonetary",
        "CustomerShare",
        "MonetaryShare",
    ),
    "kmeans_evaluation.csv": ("k", "inertia", "silhouette", "davies_bouldin"),
    "algorithm_comparison.csv": (
        "algorithm",
        "transform",
        "silhouette",
        "davies_bouldin",
        "hopkins",
        "bic",
        "aic",
    ),
}

NUMERIC_COLUMNS: dict[str, tuple[str, ...]] = {
    "rfm_customers.csv": (
        "Recency",
        "Frequency",
        "Monetary",
        "R_Score",
        "F_Score",
        "M_Score",
        "Cluster",
    ),
    "segment_summary.csv": (
        "CustomerCount",
        "MonetaryTotal",
        "AverageMonetary",
        "CustomerShare",
        "MonetaryShare",
    ),
    "kmeans_evaluation.csv": ("k", "inertia", "silhouette", "davies_bouldin"),
    "algorithm_comparison.csv": (
        "silhouette",
        "davies_bouldin",
        "hopkins",
        "bic",
        "aic",
    ),
}

IMAGE_FILES = (
    "1_rfm_segment_overview.png",
    "2_rfm_executive_summary.png",
    "3_rfm_3d_scatter.png",
    "4_rfm_action_cards.png",
    "5_kmeans_elbow_method.png",
    "6_kmeans_final_comparison.png",
    "7_algorithm_comparison.png",
)


class RunDataError(ValueError):
    """A selected run cannot safely be displayed."""


@dataclass(frozen=True)
class RunBundle:
    """Validated artifacts belonging to one pipeline run."""

    run_id: str
    run_dir: Path
    rfm_customers: pd.DataFrame
    segment_summary: pd.DataFrame
    kmeans_evaluation: pd.DataFrame
    algorithm_comparison: pd.DataFrame
    metadata: dict[str, Any]
    metadata_bytes: bytes
    images: tuple[Path, ...]


def discover_runs(output_root: Path) -> list[Path]:
    """Return run directories newest first, using modification time."""
    output_root = Path(output_root)
    if not output_root.exists() or not output_root.is_dir():
        return []
    try:
        runs = [path for path in output_root.iterdir() if path.is_dir()]
        return sorted(runs, key=lambda path: path.stat().st_mtime, reverse=True)
    except OSError as exc:
        raise RunDataError(f"无法读取运行结果目录：{exc}") from exc


def _read_table(run_dir: Path, filename: str) -> pd.DataFrame:
    path = run_dir / "tables" / filename
    if not path.is_file():
        raise RunDataError(f"运行结果缺少文件：tables/{filename}")
    try:
        frame = pd.read_csv(path, dtype={"CustomerID": "string"})
    except Exception as exc:
        raise RunDataError(f"无法读取 tables/{filename}：{exc}") from exc

    missing = [column for column in TABLE_SPECS[filename] if column not in frame.columns]
    if missing:
        raise RunDataError(
            f"tables/{filename} 格式错误，缺少字段：{', '.join(missing)}"
        )
    if frame.empty:
        raise RunDataError(f"tables/{filename} 没有可展示的数据")

    for column in NUMERIC_COLUMNS[filename]:
        try:
            frame[column] = pd.to_numeric(frame[column], errors="raise")
        except (TypeError, ValueError) as exc:
            raise RunDataError(
                f"tables/{filename} 格式错误：字段 {column} 必须为数值"
            ) from exc
    return frame


def _read_metadata(run_dir: Path) -> tuple[dict[str, Any], bytes]:
    path = run_dir / "metadata" / "run_metadata.json"
    if not path.is_file():
        raise RunDataError("运行结果缺少文件：metadata/run_metadata.json")
    try:
        raw = path.read_bytes()
        metadata = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RunDataError(f"run_metadata.json 格式错误：{exc}") from exc
    if not isinstance(metadata, dict):
        raise RunDataError("run_metadata.json 格式错误：顶层内容必须是 JSON 对象")
    return metadata, raw


def load_run(run_dir: Path) -> RunBundle:
    """Load one run after validating every dashboard artifact."""
    run_dir = Path(run_dir)
    if not run_dir.is_dir():
        raise RunDataError(f"运行结果目录不存在：{run_dir}")

    tables = {filename: _read_table(run_dir, filename) for filename in TABLE_SPECS}
    metadata, metadata_bytes = _read_metadata(run_dir)

    images = tuple(run_dir / "visualizations" / filename for filename in IMAGE_FILES)
    missing_images = [f"visualizations/{path.name}" for path in images if not path.is_file()]
    if missing_images:
        raise RunDataError(f"运行结果缺少文件：{', '.join(missing_images)}")

    return RunBundle(
        run_id=run_dir.name,
        run_dir=run_dir,
        rfm_customers=tables["rfm_customers.csv"],
        segment_summary=tables["segment_summary.csv"],
        kmeans_evaluation=tables["kmeans_evaluation.csv"],
        algorithm_comparison=tables["algorithm_comparison.csv"],
        metadata=metadata,
        metadata_bytes=metadata_bytes,
        images=images,
    )


def filter_customers(
    customers: pd.DataFrame,
    segments: list[str] | None = None,
    customer_id: str = "",
) -> pd.DataFrame:
    """Apply segment selection and a case-insensitive CustomerID search."""
    filtered = customers
    if segments:
        filtered = filtered[filtered["Segment"].astype(str).isin(segments)]
    query = customer_id.strip()
    if query:
        ids = filtered["CustomerID"].astype("string")
        normalized = ids.str.replace(r"\.0$", "", regex=True)
        normalized_query = query[:-2] if query.endswith(".0") else query
        filtered = filtered[
            normalized.str.contains(normalized_query, case=False, regex=False, na=False)
        ]
    return filtered.copy()


def compute_kpis(customers: pd.DataFrame) -> dict[str, float | int]:
    """Compute display-only KPIs from the exported customer table."""
    return {
        "customers": int(customers["CustomerID"].nunique()),
        "monetary": float(customers["Monetary"].sum()),
        "average_frequency": float(customers["Frequency"].mean()),
        "segments": int(customers["Segment"].nunique()),
    }


def dataframe_to_csv_bytes(frame: pd.DataFrame) -> bytes:
    """Create an Excel-friendly UTF-8 CSV download."""
    return frame.to_csv(index=False).encode("utf-8-sig")
