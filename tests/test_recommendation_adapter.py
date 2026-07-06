"""Tests for adapting selected run outputs to operating recommendations."""

from __future__ import annotations

import pandas as pd
import pytest

from src.recommendation_adapter import (
    RecommendationDataError,
    build_recommendation_result,
    normalize_customer_id,
    recommendation_export_frame,
)
from src.segment_recommendations import OPERATION_GROUPS, SEGMENTS, load_segment_strategies


def make_rfm(multiplier: float = 1.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "CustomerID": [f"{1000 + index}.0" for index in range(10)],
            "Recency": list(range(1, 11)),
            "Frequency": list(range(10, 0, -1)),
            "Monetary": [(index + 1) * 10.0 * multiplier for index in range(10)],
            "Segment": list(SEGMENTS),
        }
    )


def make_summary(rfm: pd.DataFrame) -> pd.DataFrame:
    summary = (
        rfm.groupby("Segment", as_index=False)
        .agg(CustomerCount=("CustomerID", "size"), MonetaryTotal=("Monetary", "sum"))
    )
    summary["CustomerShare"] = summary["CustomerCount"] / len(rfm)
    summary["MonetaryShare"] = summary["MonetaryTotal"] / rfm["Monetary"].sum()
    return summary


def build(rfm: pd.DataFrame, summary: pd.DataFrame | None = None, run_id="run_a"):
    return build_recommendation_result(
        rfm,
        make_summary(rfm) if summary is None else summary,
        {"run_id": run_id, "completed_at_utc": "2026-07-06T00:00:00Z"},
        load_segment_strategies(),
        run_id=run_id,
    )


def test_counts_and_monetary_reconcile_to_rfm_customers():
    rfm = make_rfm()
    result = build(rfm)
    assert result.recommendations["CustomerCount"].sum() == len(rfm)
    assert result.recommendations["MonetaryTotal"].sum() == pytest.approx(
        rfm["Monetary"].sum()
    )


def test_customer_and_monetary_shares_sum_to_one():
    result = build(make_rfm())
    assert result.recommendations["CustomerShare"].sum() == pytest.approx(1.0)
    assert result.recommendations["MonetaryShare"].sum() == pytest.approx(1.0)


def test_each_customer_keeps_one_segment_and_one_operation_group():
    result = build(make_rfm())
    assert result.customers["CustomerID"].is_unique
    assert result.customers["Segment"].isin(SEGMENTS).all()
    assert result.customers["推荐运营任务"].isin(OPERATION_GROUPS).all()
    assert result.customers["推荐运营任务"].notna().all()


def test_missing_segment_in_summary_is_recomputed_without_failure():
    rfm = make_rfm()
    summary = make_summary(rfm)
    summary = summary[summary["Segment"] != "Champions"]
    result = build(rfm, summary)
    champions = result.recommendations.set_index("Segment").loc["Champions"]
    assert champions["CustomerCount"] == 1
    assert champions["MonetaryTotal"] == 10.0
    assert any("分层汇总缺少Champions" in warning for warning in result.warnings)


def test_absent_segment_remains_visible_with_zero_metrics():
    rfm = make_rfm().query("Segment != 'Lost'").reset_index(drop=True)
    result = build(rfm)
    lost = result.recommendations.set_index("Segment").loc["Lost"]
    assert len(result.recommendations) == 10
    assert lost["CustomerCount"] == 0
    assert lost["MonetaryTotal"] == 0
    assert not lost["SegmentExists"]


def test_switching_run_changes_metrics_and_target_customers():
    first = build(make_rfm(), run_id="first")
    second_rfm = make_rfm(3.0).iloc[:3].copy()
    second_rfm["CustomerID"] = ["9001.0", "9002.0", "9003.0"]
    second = build(second_rfm, run_id="second")
    assert first.run_id == "first"
    assert second.run_id == "second"
    assert first.recommendations["MonetaryTotal"].sum() != second.recommendations[
        "MonetaryTotal"
    ].sum()
    assert second.customers["CustomerID"].tolist() == ["9001", "9002", "9003"]


def test_float_customer_id_is_normalized_without_changing_text_ids():
    assert normalize_customer_id(12345.0) == "12345"
    assert normalize_customer_id("12345.0") == "12345"
    assert normalize_customer_id("C-123.0") == "C-123.0"


def test_duplicate_customer_across_segments_is_rejected():
    rfm = make_rfm()
    duplicate = rfm.iloc[[0]].copy()
    duplicate["Segment"] = "Lost"
    with pytest.raises(RecommendationDataError, match="不能属于多个"):
        build(pd.concat([rfm, duplicate], ignore_index=True))


def test_export_contains_run_identity_and_csv_safe_actions():
    result = build(make_rfm(), run_id="export_run")
    exported = recommendation_export_frame(result)
    assert exported["run_id"].unique().tolist() == ["export_run"]
    assert len(exported) == 10
    assert isinstance(exported.loc[0, "Actions"], str)


def test_missing_currency_defaults_to_monetary_label():
    assert build(make_rfm()).monetary_label == "Monetary"


def test_missing_share_columns_are_recomputed():
    rfm = make_rfm()
    summary = make_summary(rfm).drop(columns=["CustomerShare", "MonetaryShare"])
    result = build(rfm, summary)
    assert result.recommendations["CustomerShare"].sum() == pytest.approx(1.0)
    assert result.recommendations["MonetaryShare"].sum() == pytest.approx(1.0)
    assert any("缺少占比字段" in warning for warning in result.warnings)


def test_empty_rfm_table_produces_zero_metrics_without_failure():
    empty = make_rfm().iloc[0:0]
    empty_summary = pd.DataFrame(
        columns=["Segment", "CustomerCount", "MonetaryTotal"]
    )
    result = build(empty, empty_summary)
    assert len(result.recommendations) == 10
    assert result.recommendations["CustomerCount"].sum() == 0
    assert result.recommendations["MonetaryShare"].sum() == 0
    assert result.customers.empty
