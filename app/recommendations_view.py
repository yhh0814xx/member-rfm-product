"""Streamlit view for run-scoped member-operation recommendations."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from src.recommendation_adapter import (
    RecommendationDataError,
    RecommendationResult,
    build_recommendation_result,
    recommendation_export_frame,
)
from src.segment_recommendations import (
    DEFAULT_CONFIG_PATH,
    OPERATION_GROUPS,
    PRIORITY_RANKS,
    SEGMENTS,
    RecommendationConfigError,
    load_segment_strategies,
)


def _csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False).encode("utf-8-sig")


def _format_money(value: float, label: str) -> str:
    return f"{value:,.2f} {label}"


def prepare_view_result(bundle, config_path: str | Path = DEFAULT_CONFIG_PATH):
    """Load configuration and adapt one RunBundle without rendering widgets."""
    strategies = load_segment_strategies(config_path)
    return build_recommendation_result(
        bundle.rfm_customers,
        bundle.segment_summary,
        bundle.metadata,
        strategies,
        run_id=bundle.run_id,
    )


def _render_group_overview(result: RecommendationResult) -> None:
    st.markdown("#### 商家行动总览")
    columns = st.columns(4)
    for column, row in zip(columns, result.group_overview.itertuples(index=False)):
        with column.container(border=True):
            st.markdown(f"##### {row.OperationGroup}")
            st.caption(f"涉及分层：{row.Segments}")
            st.metric("客户数", f"{row.CustomerCount:,}")
            st.caption(
                f"客户占比 {row.CustomerShare:.2%} · "
                f"金额贡献 {row.MonetaryShare:.2%} · 最高优先级 {row.HighestPriority}"
            )


def _render_top_recommendations(result: RecommendationResult) -> None:
    st.markdown("#### 今日优先运营建议")
    existing = result.recommendations[result.recommendations["SegmentExists"]]
    top = existing.sort_values(
        ["PriorityRank", "MonetaryShare", "CustomerCount"], ascending=False
    ).head(3)
    if top.empty:
        st.info("当前run没有可进入目标名单的客户。")
        return
    display = top[
        [
            "Segment",
            "ChineseName",
            "OperationGroup",
            "PriorityLevel",
            "CustomerCount",
            "CustomerShare",
            "MonetaryShare",
        ]
    ].rename(
        columns={
            "ChineseName": "中文名称",
            "OperationGroup": "运营任务",
            "PriorityLevel": "优先级",
            "CustomerCount": "客户数",
            "CustomerShare": "客户占比",
            "MonetaryShare": "金额贡献占比",
        }
    )
    display["客户占比"] = display["客户占比"].map(lambda value: f"{value:.2%}")
    display["金额贡献占比"] = display["金额贡献占比"].map(
        lambda value: f"{value:.2%}"
    )
    st.dataframe(display, width="stretch", hide_index=True)


def _render_recommendation_cards(result: RecommendationResult) -> None:
    st.markdown("#### 10类会员运营建议")
    filter_columns = st.columns(3)
    selected_groups = filter_columns[0].multiselect(
        "运营任务",
        list(OPERATION_GROUPS),
        key="recommendation_group_filter",
    )
    selected_priorities = filter_columns[1].multiselect(
        "运营优先级",
        list(PRIORITY_RANKS),
        key="recommendation_priority_filter",
    )
    selected_segments = filter_columns[2].multiselect(
        "会员Segment",
        list(SEGMENTS),
        key="recommendation_segment_filter",
    )

    cards = result.recommendations
    if selected_groups:
        cards = cards[cards["OperationGroup"].isin(selected_groups)]
    if selected_priorities:
        cards = cards[cards["PriorityLevel"].isin(selected_priorities)]
    if selected_segments:
        cards = cards[cards["Segment"].isin(selected_segments)]
    if cards.empty:
        st.info("当前筛选条件下没有会员运营建议。")
        return

    for row in cards.itertuples(index=False):
        label = (
            f"{row.Segment}｜{row.ChineseName}｜{row.CustomerCount:,}位 "
            f"({row.CustomerShare:.2%})｜金额{row.MonetaryTotal:,.2f} "
            f"({row.MonetaryShare:.2%})"
        )
        with st.expander(label, expanded=row.PriorityLevel in {"最高", "高"}):
            status_columns = st.columns(4)
            status_columns[0].metric("运营任务", row.OperationGroup)
            status_columns[1].metric("优先级", row.PriorityLevel)
            status_columns[2].metric("平均Recency", f"{row.AverageRecency:.1f}天")
            status_columns[3].metric("平均Frequency", f"{row.AverageFrequency:.2f}")
            if not row.SegmentExists:
                st.info("当前run中没有该分层客户，策略保留供后续run使用。")
            st.markdown(f"**客户特征：** {row.CustomerCharacteristics}")
            st.markdown(f"**推荐原因：** {row.RecommendationReason}")
            left, right = st.columns(2)
            with left:
                st.markdown("**运营目标**")
                for item in row.OperationGoal:
                    st.markdown(f"- {item}")
                st.markdown("**推荐行动**")
                for item in row.Actions:
                    st.markdown(f"- {item}")
            with right:
                st.markdown("**建议观察指标**")
                for item in row.SuccessMetrics:
                    st.markdown(f"- {item}")
                st.markdown(
                    f"**平均消费金额：** {_format_money(row.AverageMonetary, result.monetary_label)}"
                )


def _render_priority_matrix(result: RecommendationResult) -> None:
    st.markdown("#### 动态优先级矩阵")
    matrix = result.recommendations.sort_values(
        ["PriorityRank", "MonetaryShare", "CustomerCount"], ascending=False
    )[
        [
            "Segment",
            "ChineseName",
            "PriorityLevel",
            "CustomerCount",
            "CustomerShare",
            "MonetaryTotal",
            "MonetaryShare",
            "OperationGroup",
        ]
    ].rename(
        columns={
            "ChineseName": "中文名称",
            "PriorityLevel": "优先级",
            "CustomerCount": "客户数",
            "CustomerShare": "客户占比",
            "MonetaryTotal": "消费金额",
            "MonetaryShare": "金额贡献占比",
            "OperationGroup": "运营任务",
        }
    )
    matrix["客户占比"] = matrix["客户占比"].map(lambda value: f"{value:.2%}")
    matrix["金额贡献占比"] = matrix["金额贡献占比"].map(
        lambda value: f"{value:.2%}"
    )
    st.dataframe(matrix, width="stretch", hide_index=True)


def _render_target_customers(result: RecommendationResult) -> None:
    st.markdown("#### 目标客户名单")
    names = result.recommendations.set_index("Segment")["ChineseName"].to_dict()
    selected_segment = st.selectbox(
        "选择目标会员分层",
        list(SEGMENTS),
        format_func=lambda segment: f"{segment}｜{names[segment]}",
        key="recommendation_target_segment",
    )
    selected = result.customers[result.customers["Segment"] == selected_segment].copy()
    if selected.empty:
        st.info("当前run的该分层没有可下载客户。")
    else:
        st.caption(f"共{len(selected):,}位目标客户。")
        st.dataframe(selected, width="stretch", hide_index=True)

    download_columns = st.columns(2)
    recommendations = recommendation_export_frame(result)
    download_columns[0].download_button(
        "下载全部分层运营建议CSV",
        _csv_bytes(recommendations),
        file_name=f"{result.run_id}_segment_operation_recommendations.csv",
        mime="text/csv",
        key="download_segment_operation_recommendations",
    )
    download_columns[1].download_button(
        "下载当前分层客户CSV",
        _csv_bytes(selected),
        file_name=f"{result.run_id}_{selected_segment}_selected_segment_customers.csv",
        mime="text/csv",
        disabled=selected.empty,
        key="download_selected_segment_customers",
    )


def render_recommendations(bundle, config_path: str | Path = DEFAULT_CONFIG_PATH) -> None:
    """Render the complete recommendation page for the currently selected run."""
    st.subheader("会员运营建议")
    try:
        result = prepare_view_result(bundle, config_path)
    except RecommendationConfigError as exc:
        st.error(str(exc))
        st.info("请恢复完整的10类会员运营建议配置后重试。")
        return
    except RecommendationDataError as exc:
        st.error(str(exc))
        return

    if bundle.rfm_customers.empty:
        st.warning("当前run的RFM客户表为空，暂时没有可运营客户。")
    for warning in result.warnings:
        st.warning(warning)

    st.markdown("#### 当前分析信息")
    total_customers = int(result.recommendations["CustomerCount"].sum())
    total_monetary = float(result.recommendations["MonetaryTotal"].sum())
    info_columns = st.columns(4)
    info_columns[0].metric("run_id", result.run_id)
    info_columns[1].metric("生成时间", result.generated_at)
    info_columns[2].metric("客户总数", f"{total_customers:,}")
    info_columns[3].metric(
        f"{result.monetary_label}总额", f"{total_monetary:,.2f}"
    )

    _render_group_overview(result)
    _render_top_recommendations(result)
    _render_recommendation_cards(result)
    _render_priority_matrix(result)
    _render_target_customers(result)
