"""Adapt immutable run outputs to dynamic member-operation recommendations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import pandas as pd

from .segment_recommendations import (
    GROUP_SEGMENTS,
    OPERATION_GROUPS,
    PRIORITY_RANKS,
    SEGMENTS,
    SegmentStrategy,
)


RFM_REQUIRED_COLUMNS = (
    "CustomerID",
    "Recency",
    "Frequency",
    "Monetary",
    "Segment",
)


class RecommendationDataError(ValueError):
    """The selected run cannot produce reliable recommendations."""


@dataclass(frozen=True)
class RecommendationResult:
    """Presentation-ready recommendation data derived from one selected run."""

    run_id: str
    generated_at: str
    monetary_label: str
    recommendations: pd.DataFrame
    group_overview: pd.DataFrame
    customers: pd.DataFrame
    warnings: tuple[str, ...]


def normalize_customer_id(value: Any) -> str:
    """Display numeric identifiers without the CSV float suffix when safe."""
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        integer = text[:-2]
        if integer and integer.lstrip("-").isdigit():
            return integer
    return text


def _metadata_value(metadata: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = metadata.get(key)
        if value not in (None, ""):
            return value
    return None


def _monetary_label(metadata: Mapping[str, Any]) -> str:
    currency = _metadata_value(metadata, "currency", "currency_code", "monetary_unit")
    if currency is None and isinstance(metadata.get("input"), Mapping):
        currency = _metadata_value(
            metadata["input"], "currency", "currency_code", "monetary_unit"
        )
    return f"Monetary（{currency}）" if currency else "Monetary"


def _validate_customers(rfm_customers: pd.DataFrame) -> pd.DataFrame:
    missing = [column for column in RFM_REQUIRED_COLUMNS if column not in rfm_customers]
    if missing:
        raise RecommendationDataError(
            f"无法生成会员运营建议：rfm_customers.csv缺少字段：{', '.join(missing)}"
        )
    customers = rfm_customers.copy()
    for column in ("Recency", "Frequency", "Monetary"):
        customers[column] = pd.to_numeric(customers[column], errors="coerce")
    if customers[["Recency", "Frequency", "Monetary"]].isna().any().any():
        raise RecommendationDataError(
            "无法生成会员运营建议：Recency、Frequency和Monetary必须是有效数值。"
        )
    customers["Segment"] = customers["Segment"].astype("string").fillna("")
    unknown = sorted(set(customers["Segment"]) - set(SEGMENTS) - {""})
    if unknown:
        raise RecommendationDataError(
            f"无法生成会员运营建议：发现未知会员分层：{', '.join(unknown)}"
        )
    customers["CustomerID"] = customers["CustomerID"].map(normalize_customer_id)
    duplicated = customers.loc[
        customers["CustomerID"].ne("") & customers["CustomerID"].duplicated(False),
        ["CustomerID", "Segment"],
    ]
    if not duplicated.empty:
        conflicting = duplicated.groupby("CustomerID")["Segment"].nunique()
        if (conflicting > 1).any():
            raise RecommendationDataError("同一CustomerID不能属于多个原始Segment。")
        raise RecommendationDataError("rfm_customers.csv中存在重复CustomerID，无法可靠汇总。")
    return customers


def _summary_warnings(
    computed: pd.DataFrame, segment_summary: pd.DataFrame
) -> list[str]:
    warnings: list[str] = []
    required = {"Segment", "CustomerCount", "MonetaryTotal"}
    if not required.issubset(segment_summary.columns):
        warnings.append("分层汇总字段不完整，人数与金额已根据RFM客户表重新计算。")
        return warnings
    if not {"CustomerShare", "MonetaryShare"}.issubset(segment_summary.columns):
        warnings.append("分层汇总缺少占比字段，占比已根据RFM客户表重新计算。")
    indexed = segment_summary.set_index(segment_summary["Segment"].astype(str))
    for row in computed.itertuples(index=False):
        if row.CustomerCount == 0:
            continue
        if row.Segment not in indexed.index:
            warnings.append(f"分层汇总缺少{row.Segment}，该分层指标已根据RFM客户表补算。")
            continue
        summary_row = indexed.loc[row.Segment]
        if isinstance(summary_row, pd.DataFrame):
            warnings.append(f"分层汇总中的{row.Segment}重复，已使用RFM客户表结果。")
            continue
        try:
            count_matches = int(summary_row["CustomerCount"]) == row.CustomerCount
            money_matches = abs(float(summary_row["MonetaryTotal"]) - row.MonetaryTotal) <= 0.01
        except (TypeError, ValueError):
            count_matches = money_matches = False
        if not count_matches or not money_matches:
            warnings.append(f"{row.Segment}的分层汇总与客户表不一致，已使用客户表结果。")
    return warnings


def build_recommendation_result(
    rfm_customers: pd.DataFrame,
    segment_summary: pd.DataFrame,
    metadata: Mapping[str, Any],
    strategies: Mapping[str, SegmentStrategy],
    *,
    run_id: str | None = None,
) -> RecommendationResult:
    """Build all cards, group metrics and target customers from the selected run."""
    customers = _validate_customers(rfm_customers)
    if set(strategies) != set(SEGMENTS):
        raise RecommendationDataError("会员运营建议配置没有完整覆盖当前10类Segment。")

    customer_total = int(len(customers))
    monetary_total = float(customers["Monetary"].sum()) if customer_total else 0.0
    rows: list[dict[str, Any]] = []
    for segment in SEGMENTS:
        strategy = strategies[segment]
        segment_customers = customers[customers["Segment"] == segment]
        count = int(len(segment_customers))
        money = float(segment_customers["Monetary"].sum()) if count else 0.0
        customer_share = count / customer_total if customer_total else 0.0
        monetary_share = money / monetary_total if monetary_total else 0.0
        average_monetary = money / count if count else 0.0
        average_recency = float(segment_customers["Recency"].mean()) if count else 0.0
        average_frequency = float(segment_customers["Frequency"].mean()) if count else 0.0
        if count:
            reason = (
                f"当前run中该分层共有{count:,}位客户，占全部客户{customer_share:.2%}，"
                f"贡献{monetary_share:.2%}的消费金额；平均Recency为{average_recency:.1f}天，"
                f"平均Frequency为{average_frequency:.2f}。{strategy.recommendation_reason}"
            )
        else:
            reason = (
                "当前run中没有该分层客户，暂时无需建立目标名单；"
                f"出现该分层后可采用以下策略。{strategy.recommendation_reason}"
            )
        rows.append(
            {
                "Segment": segment,
                "ChineseName": strategy.chinese_name,
                "OperationGroup": strategy.operation_group,
                "PriorityLevel": strategy.priority_level,
                "PriorityRank": PRIORITY_RANKS[strategy.priority_level],
                "CustomerCharacteristics": strategy.customer_characteristics,
                "OperationGoal": strategy.operation_goal,
                "RecommendationReason": reason,
                "Actions": strategy.actions,
                "SuccessMetrics": strategy.success_metrics,
                "CustomerCount": count,
                "CustomerShare": customer_share,
                "MonetaryTotal": money,
                "MonetaryShare": monetary_share,
                "AverageMonetary": average_monetary,
                "AverageRecency": average_recency,
                "AverageFrequency": average_frequency,
                "SegmentExists": bool(count),
            }
        )
    recommendations = pd.DataFrame(rows)
    warnings = _summary_warnings(recommendations, segment_summary)

    group_rows: list[dict[str, Any]] = []
    for group in OPERATION_GROUPS:
        group_frame = recommendations[recommendations["OperationGroup"] == group]
        highest = group_frame.sort_values(
            ["PriorityRank", "MonetaryShare", "CustomerCount"], ascending=False
        ).iloc[0]
        group_rows.append(
            {
                "OperationGroup": group,
                "Segments": "、".join(GROUP_SEGMENTS[group]),
                "CustomerCount": int(group_frame["CustomerCount"].sum()),
                "CustomerShare": float(group_frame["CustomerShare"].sum()),
                "MonetaryTotal": float(group_frame["MonetaryTotal"].sum()),
                "MonetaryShare": float(group_frame["MonetaryShare"].sum()),
                "HighestPriority": str(highest["PriorityLevel"]),
            }
        )

    strategy_groups = {segment: strategies[segment].operation_group for segment in SEGMENTS}
    strategy_priorities = {segment: strategies[segment].priority_level for segment in SEGMENTS}
    target_customers = customers.loc[
        customers["Segment"].isin(SEGMENTS),
        ["CustomerID", "Recency", "Frequency", "Monetary", "Segment"],
    ].copy()
    target_customers["推荐运营任务"] = target_customers["Segment"].map(strategy_groups)
    target_customers["推荐优先级"] = target_customers["Segment"].map(strategy_priorities)

    resolved_run_id = str(run_id or metadata.get("run_id") or "未提供")
    generated_at = str(
        _metadata_value(metadata, "completed_at_utc", "generated_at", "started_at_utc")
        or "未提供"
    )
    return RecommendationResult(
        run_id=resolved_run_id,
        generated_at=generated_at,
        monetary_label=_monetary_label(metadata),
        recommendations=recommendations,
        group_overview=pd.DataFrame(group_rows),
        customers=target_customers,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def recommendation_export_frame(result: RecommendationResult) -> pd.DataFrame:
    """Return a flat, CSV-safe representation of all ten recommendations."""
    frame = result.recommendations.drop(columns=["PriorityRank"]).copy()
    for column in ("OperationGoal", "Actions", "SuccessMetrics"):
        frame[column] = frame[column].map(lambda values: "；".join(values))
    frame.insert(0, "run_id", result.run_id)
    frame.insert(1, "generated_at", result.generated_at)
    return frame
