"""Load and validate configurable operating strategies for RFM segments."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SEGMENTS = (
    "Champions",
    "Loyal Customers",
    "Potential Loyalists",
    "New Customers",
    "Promising",
    "Need Attention",
    "At Risk",
    "Can't Lose Them",
    "Hibernating",
    "Lost",
)

OPERATION_GROUPS = (
    "重点维护",
    "成长培育",
    "流失挽回",
    "低成本唤醒",
)

GROUP_SEGMENTS = {
    "重点维护": ("Champions", "Loyal Customers"),
    "成长培育": ("Potential Loyalists", "New Customers", "Promising"),
    "流失挽回": ("Need Attention", "At Risk", "Can't Lose Them"),
    "低成本唤醒": ("Hibernating", "Lost"),
}

PRIORITY_RANKS = {
    "最高": 6,
    "高": 5,
    "中高": 4,
    "中": 3,
    "中低": 2,
    "低": 1,
}

HIGH_PRIORITY_LEVELS = frozenset({"最高", "高"})

TASK_COLORS = {
    "重点维护": "#2563EB",
    "成长培育": "#16A34A",
    "流失挽回": "#EA580C",
    "低成本唤醒": "#7C3AED",
}


def rank_priority_actions(recommendations, top_n: int = 3):
    """Return the top actionable segments using the agreed business order."""
    existing = recommendations[recommendations["SegmentExists"]].copy()
    if existing.empty:
        return existing.head(0)
    return existing.sort_values(
        ["PriorityRank", "MonetaryShare", "CustomerCount"],
        ascending=False,
    ).head(top_n)

REQUIRED_FIELDS = (
    "Segment",
    "ChineseName",
    "OperationGroup",
    "PriorityLevel",
    "CustomerCharacteristics",
    "OperationGoal",
    "RecommendationReason",
    "Actions",
    "SuccessMetrics",
)

DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "segment_recommendations_zh.json"
)


class RecommendationConfigError(ValueError):
    """The operating-strategy configuration is missing or invalid."""


@dataclass(frozen=True)
class SegmentStrategy:
    """Validated, presentation-neutral strategy for one authoritative segment."""

    segment: str
    chinese_name: str
    operation_group: str
    priority_level: str
    customer_characteristics: str
    operation_goal: tuple[str, ...]
    recommendation_reason: str
    actions: tuple[str, ...]
    success_metrics: tuple[str, ...]


def _text(value: Any, field: str, segment: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RecommendationConfigError(
            f"推荐配置错误：{segment} 的 {field} 必须是非空文本。"
        )
    return value.strip()


def _text_list(value: Any, field: str, segment: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise RecommendationConfigError(
            f"推荐配置错误：{segment} 的 {field} 必须是非空列表。"
        )
    return tuple(_text(item, field, segment) for item in value)


def load_segment_strategies(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> dict[str, SegmentStrategy]:
    """Return all ten strategies after strict schema and coverage validation."""
    path = Path(config_path)
    if not path.is_file():
        raise RecommendationConfigError(f"缺少会员运营建议配置文件：{path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecommendationConfigError(f"无法读取会员运营建议配置：{exc}") from exc
    if not isinstance(payload, list):
        raise RecommendationConfigError("推荐配置错误：顶层内容必须是列表。")

    strategies: dict[str, SegmentStrategy] = {}
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise RecommendationConfigError(f"推荐配置错误：第{index}项必须是对象。")
        missing = [field for field in REQUIRED_FIELDS if field not in item]
        if missing:
            raise RecommendationConfigError(
                f"推荐配置错误：第{index}项缺少字段：{', '.join(missing)}"
            )
        segment = _text(item["Segment"], "Segment", f"第{index}项")
        if segment in strategies:
            raise RecommendationConfigError(f"推荐配置错误：Segment重复：{segment}")
        operation_group = _text(item["OperationGroup"], "OperationGroup", segment)
        priority_level = _text(item["PriorityLevel"], "PriorityLevel", segment)
        if operation_group not in OPERATION_GROUPS:
            raise RecommendationConfigError(
                f"推荐配置错误：{segment} 的运营任务无效：{operation_group}"
            )
        if priority_level not in PRIORITY_RANKS:
            raise RecommendationConfigError(
                f"推荐配置错误：{segment} 的优先级无效：{priority_level}"
            )
        strategies[segment] = SegmentStrategy(
            segment=segment,
            chinese_name=_text(item["ChineseName"], "ChineseName", segment),
            operation_group=operation_group,
            priority_level=priority_level,
            customer_characteristics=_text(
                item["CustomerCharacteristics"], "CustomerCharacteristics", segment
            ),
            operation_goal=_text_list(item["OperationGoal"], "OperationGoal", segment),
            recommendation_reason=_text(
                item["RecommendationReason"], "RecommendationReason", segment
            ),
            actions=_text_list(item["Actions"], "Actions", segment),
            success_metrics=_text_list(
                item["SuccessMetrics"], "SuccessMetrics", segment
            ),
        )

    missing_segments = [segment for segment in SEGMENTS if segment not in strategies]
    extra_segments = [segment for segment in strategies if segment not in SEGMENTS]
    if missing_segments or extra_segments:
        details = []
        if missing_segments:
            details.append(f"缺少分层：{', '.join(missing_segments)}")
        if extra_segments:
            details.append(f"未知分层：{', '.join(extra_segments)}")
        raise RecommendationConfigError("推荐配置未完整覆盖当前10类会员；" + "；".join(details))

    for group, expected in GROUP_SEGMENTS.items():
        actual = tuple(segment for segment in SEGMENTS if strategies[segment].operation_group == group)
        if actual != expected:
            raise RecommendationConfigError(
                f"推荐配置错误：运营任务“{group}”的分层映射不符合项目约定。"
            )
    return strategies
