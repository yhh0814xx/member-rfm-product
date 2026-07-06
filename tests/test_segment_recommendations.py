"""Tests for the ten-segment operating-strategy configuration."""

from __future__ import annotations

import json

import pytest

from src.segment_recommendations import (
    DEFAULT_CONFIG_PATH,
    GROUP_SEGMENTS,
    OPERATION_GROUPS,
    REQUIRED_FIELDS,
    SEGMENTS,
    RecommendationConfigError,
    load_segment_strategies,
)


def test_all_ten_segments_have_complete_configuration():
    strategies = load_segment_strategies()
    assert tuple(strategies) == SEGMENTS
    assert len(strategies) == 10
    for strategy in strategies.values():
        assert strategy.chinese_name
        assert strategy.customer_characteristics
        assert strategy.operation_goal
        assert strategy.recommendation_reason
        assert strategy.actions
        assert strategy.success_metrics


def test_four_operation_groups_cover_each_segment_once():
    flattened = [segment for group in OPERATION_GROUPS for segment in GROUP_SEGMENTS[group]]
    assert sorted(flattened) == sorted(SEGMENTS)
    assert len(flattened) == len(set(flattened)) == 10


def test_configuration_file_contains_required_external_schema():
    payload = json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    assert len(payload) == 10
    assert all(set(REQUIRED_FIELDS).issubset(item) for item in payload)


def test_missing_configuration_has_chinese_error(tmp_path):
    with pytest.raises(RecommendationConfigError, match="缺少会员运营建议配置文件"):
        load_segment_strategies(tmp_path / "missing.json")


def test_missing_segment_configuration_is_rejected(tmp_path):
    payload = json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))[:-1]
    path = tmp_path / "incomplete.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(RecommendationConfigError, match="未完整覆盖当前10类会员"):
        load_segment_strategies(path)


def test_configuration_has_no_reference_specific_hardcoding():
    text = DEFAULT_CONFIG_PATH.read_text(encoding="utf-8").lower()
    forbidden = ("amazon", "prime day", "klaviyo", "$", "clv", "seller central")
    assert all(term not in text for term in forbidden)
