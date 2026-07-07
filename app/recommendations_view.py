"""Streamlit workbench for merchant-facing member operations."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from app.action_status_store import load_statuses, save_status
from app.global_filters import normalize_customer_ids
from src.customer_action_engine import (
    ACTION_STATUSES,
    DEFAULT_TEMPLATE_PATH,
    CustomerActionConfigError,
    build_customer_action_queue,
    load_message_templates,
)
from src.recommendation_adapter import (
    RecommendationDataError,
    RecommendationResult,
    build_recommendation_result,
    high_priority_metrics,
    priority_actions_frame,
    recommendation_export_frame,
    value_risk_matrix_frame,
)
from src.segment_recommendations import (
    DEFAULT_CONFIG_PATH,
    OPERATION_GROUPS,
    PRIORITY_RANKS,
    SEGMENTS,
    TASK_COLORS,
    RecommendationConfigError,
    load_segment_strategies,
)


ACTION_TABLE_COLUMNS = [
    "CustomerID",
    "ChineseName",
    "Segment",
    "OperationGroup",
    "PriorityLevel",
    "ActionPriorityLabel",
    "ActionPriorityScore",
    "Recency",
    "Frequency",
    "MonetaryCompact",
    "LastPurchaseDate",
    "TopPurchasedProduct",
    "ContactReasonShort",
    "NextBestAction",
    "MessageEntry",
    "Status",
    "MerchantNote",
]

DOWNLOAD_COLUMNS = [
    "CustomerID",
    "ChineseName",
    "Segment",
    "OperationGroup",
    "PriorityLevel",
    "ActionPriorityLabel",
    "ActionPriorityScore",
    "Recency",
    "Frequency",
    "Monetary",
    "LastPurchaseDate",
    "LastPurchasedProducts",
    "TopPurchasedProduct",
    "OrderCount",
    "TotalQuantity",
    "ContactReason",
    "NextBestAction",
    "ShortMessage",
    "CareMessage",
    "AvoidAction",
    "Status",
    "MerchantNote",
]


def _csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False).encode("utf-8-sig")


def _compact_number(value: float) -> str:
    value = float(value or 0)
    absolute = abs(value)
    if absolute >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if absolute >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:,.0f}"


def _format_money(value: float, label: str = "Monetary") -> str:
    return f"{label} {_compact_number(value)}"


def _format_money_full(value: float, label: str = "Monetary") -> str:
    return f"{label} {float(value or 0):,.2f}"


def _format_percent(value: float) -> str:
    return f"{value:.2%}"


def _inject_css() -> None:
    st.markdown(
        """
        <style>
        .rfm-badge {
            display: inline-block;
            padding: 0.12rem 0.45rem;
            border-radius: 0.4rem;
            color: #ffffff;
            font-size: 0.78rem;
            font-weight: 700;
            line-height: 1.5;
        }
        .rfm-card-title {
            font-size: 1.02rem;
            font-weight: 700;
            margin-bottom: 0.2rem;
        }
        .rfm-reason {
            max-height: 2.8rem;
            overflow: hidden;
            line-height: 1.4;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _badge(text: str, color: str) -> None:
    st.markdown(
        f'<span class="rfm-badge" style="background:{color};">{text}</span>',
        unsafe_allow_html=True,
    )


def prepare_view_result(
    bundle,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    *,
    rfm_customers: pd.DataFrame | None = None,
    segment_summary: pd.DataFrame | None = None,
):
    """Load configuration and adapt one RunBundle without rendering widgets."""
    strategies = load_segment_strategies(config_path)
    return build_recommendation_result(
        bundle.rfm_customers if rfm_customers is None else rfm_customers,
        bundle.segment_summary if segment_summary is None else segment_summary,
        bundle.metadata,
        strategies,
        run_id=bundle.run_id,
    )


def prepare_action_queue(
    bundle,
    *,
    rfm_customers: pd.DataFrame,
    transactions: pd.DataFrame | None,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    template_path: str | Path = DEFAULT_TEMPLATE_PATH,
) -> pd.DataFrame:
    """Build the current filtered customer action queue for tests and UI."""
    strategies = load_segment_strategies(config_path)
    templates = load_message_templates(template_path)
    customer_ids = (
        rfm_customers["CustomerID"].map(lambda value: str(value).replace(".0", ""))
        if "CustomerID" in rfm_customers
        else pd.Series(dtype=str)
    )
    statuses = load_statuses(str(bundle.run_id), customer_ids.dropna().tolist())
    return build_customer_action_queue(
        rfm_customers,
        transactions,
        strategies,
        templates,
        statuses=statuses,
    )


def render_filter_summary(summary: tuple[str, ...] | None) -> None:
    with st.container(border=True):
        st.markdown("##### 当前筛选摘要")
        st.caption("；".join(summary) if summary else "筛选条件：全部数据")


def _queue_metrics(queue: pd.DataFrame) -> None:
    total_monetary = float(queue["Monetary"].sum()) if not queue.empty else 0.0
    high_threshold = float(queue["Monetary"].quantile(0.75)) if not queue.empty else 0.0
    high_value = int(queue["Monetary"].ge(high_threshold).sum()) if not queue.empty else 0
    columns = st.columns(4)
    columns[0].metric("待联系客户数", f"{len(queue):,}")
    columns[1].metric(
        "立即处理客户数",
        f"{int(queue['ActionPriorityLabel'].eq('立即处理').sum()) if not queue.empty else 0:,}",
    )
    columns[2].metric("高价值客户数", f"{high_value:,}")
    columns[3].metric("当前客户Monetary总额", _format_money(total_monetary))
    columns[3].caption(_format_money_full(total_monetary))


def _filter_action_queue(queue: pd.DataFrame) -> pd.DataFrame:
    if queue.empty:
        return queue.copy()
    filter_columns = st.columns([1.1, 1.1, 1.2, 1.1, 1.4])
    selected_priority = filter_columns[0].multiselect(
        "处理优先级",
        sorted(queue["ActionPriorityLabel"].dropna().unique().tolist()),
        key="workbench_priority_filter",
    )
    selected_segments = filter_columns[1].multiselect(
        "Segment",
        list(SEGMENTS),
        key="workbench_segment_filter",
    )
    selected_groups = filter_columns[2].multiselect(
        "运营任务",
        list(OPERATION_GROUPS),
        key="workbench_group_filter",
    )
    selected_statuses = filter_columns[3].multiselect(
        "处理状态",
        list(ACTION_STATUSES),
        key="workbench_status_filter",
    )
    query = filter_columns[4].text_input(
        "CustomerID搜索",
        key="workbench_customer_query",
    )
    filtered = queue.copy()
    if selected_priority:
        filtered = filtered[filtered["ActionPriorityLabel"].isin(selected_priority)]
    if selected_segments:
        filtered = filtered[filtered["Segment"].isin(selected_segments)]
    if selected_groups:
        filtered = filtered[filtered["OperationGroup"].isin(selected_groups)]
    if selected_statuses:
        filtered = filtered[filtered["Status"].isin(selected_statuses)]
    if query.strip():
        filtered = filtered[
            filtered["CustomerID"].astype(str).str.contains(query.strip(), case=False, na=False)
        ]

    sort_label = st.selectbox(
        "队列排序",
        ["默认运营优先", "Monetary从高到低", "Recency风险从高到低", "Frequency从高到低"],
        key="workbench_queue_sort",
    )
    if sort_label == "Monetary从高到低":
        filtered = filtered.sort_values(["Monetary", "Recency", "Frequency"], ascending=False)
    elif sort_label == "Recency风险从高到低":
        filtered = filtered.sort_values(["Recency", "Monetary", "Frequency"], ascending=False)
    elif sort_label == "Frequency从高到低":
        filtered = filtered.sort_values(["Frequency", "Monetary", "Recency"], ascending=False)
    return filtered.reset_index(drop=True)


def _display_queue(queue: pd.DataFrame) -> pd.DataFrame:
    display = queue.copy()
    display["MonetaryCompact"] = display["Monetary"].map(_compact_number)
    display["ContactReasonShort"] = display["ContactReason"].map(
        lambda value: str(value)[:88] + ("..." if len(str(value)) > 88 else "")
    )
    display["MessageEntry"] = "查看话术"
    return display[ACTION_TABLE_COLUMNS]


def render_today_todo(queue: pd.DataFrame) -> pd.DataFrame:
    """Render the first-screen action queue."""
    _queue_metrics(queue)
    st.caption("处理状态会持久化保存在本机 SQLite：data/merchant_actions.sqlite。")
    st.markdown("#### 客户行动队列")
    if queue.empty:
        st.info("当前筛选条件下没有待运营客户，请调整全局筛选条件。")
        return queue
    filtered = _filter_action_queue(queue)
    if filtered.empty:
        st.info("当前队列筛选条件下没有匹配客户。")
        return filtered
    event = st.dataframe(
        _display_queue(filtered),
        width="stretch",
        hide_index=True,
        key="workbench_action_queue",
        on_select="rerun",
        selection_mode="single-row",
    )
    rows = getattr(getattr(event, "selection", None), "rows", []) or []
    if rows:
        st.session_state["workbench_selected_customer"] = filtered.iloc[int(rows[0])]["CustomerID"]
    customer_options = filtered["CustomerID"].astype(str).tolist()
    selected_customer = st.selectbox(
        "选择客户",
        customer_options,
        index=customer_options.index(st.session_state.get("workbench_selected_customer"))
        if st.session_state.get("workbench_selected_customer") in customer_options
        else 0,
        key="workbench_customer_selector",
    )
    st.session_state["workbench_selected_customer"] = selected_customer
    st.download_button(
        "下载当前客户行动名单CSV",
        _csv_bytes(filtered[DOWNLOAD_COLUMNS]),
        file_name="customer_action_queue_filtered.csv",
        mime="text/csv",
        key="download_workbench_action_queue",
    )
    return filtered


def _customer_transactions(transactions: pd.DataFrame | None, customer_id: str) -> pd.DataFrame:
    if transactions is None or transactions.empty or "CustomerID" not in transactions:
        return pd.DataFrame()
    normalized = normalize_customer_ids(transactions["CustomerID"])
    return transactions.loc[normalized.eq(str(customer_id))].copy()


def _render_message_blocks(row: pd.Series) -> None:
    st.markdown("##### 推荐话术")
    st.markdown("**简短首条消息**")
    st.code(str(row["ShortMessage"]), language="text")
    st.markdown("**关怀回访消息**")
    st.code(str(row["CareMessage"]), language="text")
    st.markdown("**不建议采取的动作**")
    st.warning(str(row["AvoidAction"]))


def render_customer_detail(
    queue: pd.DataFrame, transactions: pd.DataFrame | None, run_id: str, *, key_prefix: str
) -> None:
    """Render the selected customer's 360 detail, messages and status controls."""
    if queue.empty:
        st.info("当前没有可查看的客户详情。")
        return
    selected = st.session_state.get("workbench_selected_customer") or str(queue.iloc[0]["CustomerID"])
    if selected not in queue["CustomerID"].astype(str).tolist():
        selected = str(queue.iloc[0]["CustomerID"])
    row = queue[queue["CustomerID"].astype(str).eq(str(selected))].iloc[0]

    st.markdown(f"#### 客户 {row['CustomerID']}")
    summary_columns = st.columns(5)
    summary_columns[0].metric("Segment", row["Segment"])
    summary_columns[1].metric("Recency", f"{row['Recency']:,.0f}")
    summary_columns[2].metric("Frequency", f"{row['Frequency']:,.0f}")
    summary_columns[3].metric("Monetary", _compact_number(row["Monetary"]))
    summary_columns[3].caption(f"完整值：{row['Monetary']:,.2f}")
    summary_columns[4].metric("运营优先分", f"{row['ActionPriorityScore']:.2f}")

    left, right = st.columns([1.1, 1])
    with left:
        st.markdown("##### 联系原因与下一步")
        _badge(str(row["ActionPriorityLabel"]), TASK_COLORS.get(row["OperationGroup"], "#475467"))
        st.write(row["ContactReason"])
        st.markdown(f"**下一步行动：** {row['NextBestAction']}")
        st.markdown("##### 商品与订单概况")
        st.write(f"最近购买日期：{row['LastPurchaseDate'] or '暂无'}")
        st.write(f"最近购买商品：{row['LastPurchasedProducts'] or '暂无'}")
        st.write(f"最常购买商品：{row['TopPurchasedProduct'] or '暂无'}")
        st.write(f"订单数：{int(row['OrderCount']):,}；购买数量：{row['TotalQuantity']:,.0f}")
    with right:
        _render_message_blocks(row)

    status_columns = st.columns([1, 2, 1])
    status = status_columns[0].selectbox(
        "处理状态",
        list(ACTION_STATUSES),
        index=list(ACTION_STATUSES).index(row["Status"]) if row["Status"] in ACTION_STATUSES else 0,
        key=f"{key_prefix}_status_{row['CustomerID']}",
    )
    note = status_columns[1].text_area(
        "商家备注",
        value=str(row["MerchantNote"]),
        key=f"{key_prefix}_note_{row['CustomerID']}",
        height=90,
    )
    if status_columns[2].button("保存状态", key=f"{key_prefix}_save_{row['CustomerID']}"):
        try:
            save_status(str(run_id), str(row["CustomerID"]), status, note)
        except RuntimeError as exc:
            st.error(str(exc))
        else:
            st.success("处理状态已保存。")
            st.rerun()

    customer_tx = _customer_transactions(transactions, str(row["CustomerID"]))
    with st.expander("查看完整交易", expanded=False):
        if customer_tx.empty:
            st.info("当前筛选范围内没有该客户交易记录。")
        else:
            st.dataframe(customer_tx, width="stretch", hide_index=True)


def render_recommendation_overview(result: RecommendationResult) -> None:
    total_customers = int(result.recommendations["CustomerCount"].sum())
    total_monetary = float(result.recommendations["MonetaryTotal"].sum())
    high_count, high_monetary = high_priority_metrics(result)

    metric_columns = st.columns(4)
    metric_columns[0].metric("当前筛选客户数", f"{total_customers:,}")
    metric_columns[1].metric("当前客户Monetary总额", _format_money(total_monetary))
    metric_columns[1].caption(_format_money_full(total_monetary))
    metric_columns[2].metric("高优先级客户数", f"{high_count:,}")
    metric_columns[3].metric("高优先级客户Monetary贡献", _format_money(high_monetary))
    metric_columns[3].caption(_format_money_full(high_monetary))

    if total_customers == 0:
        st.warning("当前筛选条件下没有匹配客户，请调整全局筛选条件。")
        return

    st.markdown("#### 运营任务卡片")
    card_columns = st.columns(4)
    for index, row in enumerate(result.group_overview.itertuples(index=False)):
        color = TASK_COLORS.get(row.OperationGroup, "#475467")
        with card_columns[index % 4].container(border=True):
            st.markdown(f'<div class="rfm-card-title">{row.OperationGroup}</div>', unsafe_allow_html=True)
            _badge(row.HighestPriority, color)
            st.caption(f"包含分层：{row.Segments}")
            st.metric("客户人数", f"{row.CustomerCount:,}")
            st.caption(f"客户占比：{_format_percent(row.CustomerShare)}")
            st.metric("Monetary总额", _format_money(row.MonetaryTotal))
            st.caption(f"Monetary贡献占比：{_format_percent(row.MonetaryShare)}")

    render_priority_actions(result)
    chart_left, chart_right = st.columns([1.2, 1])
    with chart_left:
        render_value_risk_matrix(result)
    with chart_right:
        st.markdown("#### 运营任务对比")
        comparison = result.group_overview.melt(
            id_vars="OperationGroup",
            value_vars=["CustomerCount", "MonetaryTotal"],
            var_name="指标",
            value_name="数值",
        )
        comparison["指标"] = comparison["指标"].map({"CustomerCount": "客户数量", "MonetaryTotal": "Monetary贡献"})
        fig = px.bar(
            comparison,
            x="数值",
            y="OperationGroup",
            color="指标",
            orientation="h",
            barmode="group",
            color_discrete_sequence=["#2563EB", "#16A34A"],
            labels={"OperationGroup": "运营任务"},
        )
        fig.update_layout(height=360, margin=dict(l=10, r=10, t=20, b=10))
        st.plotly_chart(fig, width="stretch")


def render_priority_actions(result: RecommendationResult) -> None:
    st.markdown("#### 分层Top 3")
    top = priority_actions_frame(result)
    if top.empty:
        st.info("当前筛选范围内没有可运营的目标客户。")
        return
    for index, row in enumerate(top.itertuples(index=False), start=1):
        with st.container(border=True):
            st.markdown(f"##### {index}. {row.ChineseName}（{row.Segment}）")
            columns = st.columns([1, 1, 2])
            columns[0].metric("客户数量", f"{row.CustomerCount:,}")
            columns[1].metric("Monetary贡献", _format_percent(row.MonetaryShare))
            with columns[2]:
                _badge(row.OperationGroup, TASK_COLORS.get(row.OperationGroup, "#475467"))
                st.caption(f"优先级：{row.PriorityLevel}")
            st.write(row.RecommendationReason)
            for item in list(row.Actions)[:3]:
                st.markdown(f"- {item}")


def render_value_risk_matrix(result: RecommendationResult) -> pd.DataFrame:
    st.markdown("#### 客户价值-流失风险矩阵")
    matrix = value_risk_matrix_frame(result)
    if matrix.empty:
        st.info("当前筛选范围内没有可绘制的分层数据。")
        return matrix
    fig = px.scatter(
        matrix,
        x="AverageMonetary",
        y="AverageRecency",
        size="CustomerCount",
        color="OperationGroup",
        text="ChineseName",
        hover_name="Segment",
        color_discrete_map=TASK_COLORS,
        labels={"AverageMonetary": "AvgMonetary", "AverageRecency": "AvgRecency / 流失风险代理值", "OperationGroup": "运营任务"},
    )
    fig.update_traces(textposition="top center")
    fig.update_layout(height=380, margin=dict(l=10, r=10, t=20, b=10))
    st.plotly_chart(fig, width="stretch")
    st.caption("该矩阵基于现有RFM指标形成，用于辅助运营排序，不代表单独训练的流失预测模型。")
    return matrix


def _filtered_segments_for_strategy(result: RecommendationResult) -> pd.DataFrame:
    filter_columns = st.columns(3)
    selected_groups = filter_columns[0].multiselect("运营任务", list(OPERATION_GROUPS), key="recommendation_strategy_group_filter")
    selected_priorities = filter_columns[1].multiselect("优先级", list(PRIORITY_RANKS), key="recommendation_strategy_priority_filter")
    selected_segments = filter_columns[2].multiselect("Segment", list(SEGMENTS), key="recommendation_strategy_segment_filter")
    cards = result.recommendations.copy()
    if selected_groups:
        cards = cards[cards["OperationGroup"].isin(selected_groups)]
    if selected_priorities:
        cards = cards[cards["PriorityLevel"].isin(selected_priorities)]
    if selected_segments:
        cards = cards[cards["Segment"].isin(selected_segments)]
    return cards.sort_values(["PriorityRank", "MonetaryShare", "CustomerCount"], ascending=False)


def render_segment_strategy_cards(result: RecommendationResult) -> None:
    st.markdown("#### 分层策略")
    cards = _filtered_segments_for_strategy(result)
    if cards.empty:
        st.info("当前筛选条件下没有匹配的会员分层策略。")
        return
    for row in cards.itertuples(index=False):
        color = TASK_COLORS.get(row.OperationGroup, "#475467")
        with st.container(border=True):
            header_columns = st.columns([2.0, 1.0, 1.0, 1.0])
            with header_columns[0]:
                st.markdown(f"##### {row.ChineseName}")
                st.caption(row.Segment)
                _badge(row.PriorityLevel, color)
            header_columns[1].metric("客户数", f"{row.CustomerCount:,}")
            header_columns[1].caption(f"客户占比：{_format_percent(row.CustomerShare)}")
            header_columns[2].metric("Monetary总额", _format_money(row.MonetaryTotal))
            header_columns[2].caption(f"贡献占比：{_format_percent(row.MonetaryShare)}")
            header_columns[3].metric("运营任务", row.OperationGroup)
            with st.expander("查看策略详情", expanded=False):
                st.markdown("**客户特征**")
                st.write(row.CustomerCharacteristics)
                st.markdown("**推荐原因**")
                st.write(row.RecommendationReason)
                st.markdown("**具体行动**")
                for item in list(row.Actions)[:5]:
                    st.markdown(f"- {item}")
                st.markdown("**建议观察指标**")
                for item in row.SuccessMetrics:
                    st.markdown(f"- {item}")


def render_recommendations(
    bundle,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    *,
    rfm_customers: pd.DataFrame | None = None,
    segment_summary: pd.DataFrame | None = None,
    filtered_transactions: pd.DataFrame | None = None,
    filter_summary: tuple[str, ...] | None = None,
) -> None:
    """Render the member-operation workbench for the selected run."""
    _inject_css()
    st.subheader("会员运营工作台")
    st.info("当前展示对象受全局筛选条件限制；RFM指标、会员分层和聚类结果仍来自当前完整run。")
    displayed_customers = bundle.rfm_customers if rfm_customers is None else rfm_customers
    displayed_summary = bundle.segment_summary if segment_summary is None else segment_summary
    try:
        result = prepare_view_result(
            bundle,
            config_path,
            rfm_customers=displayed_customers,
            segment_summary=displayed_summary,
        )
        queue = prepare_action_queue(
            bundle,
            rfm_customers=displayed_customers,
            transactions=filtered_transactions,
            config_path=config_path,
        )
    except (RecommendationConfigError, CustomerActionConfigError) as exc:
        st.error(str(exc))
        return
    except RecommendationDataError as exc:
        st.error(str(exc))
        return

    render_filter_summary(filter_summary)
    for warning in result.warnings:
        st.warning(warning)

    todo_tab, detail_tab, analysis_tab = st.tabs(["今日待办", "客户详情与话术", "分层分析"])
    with todo_tab:
        filtered_queue = render_today_todo(queue)
        if not filtered_queue.empty:
            st.markdown("#### 当前选中客户概览")
            render_customer_detail(
                filtered_queue,
                filtered_transactions,
                str(bundle.run_id),
                key_prefix="workbench_todo_detail",
            )
    with detail_tab:
        render_customer_detail(
            queue,
            filtered_transactions,
            str(bundle.run_id),
            key_prefix="workbench_full_detail",
        )
    with analysis_tab:
        render_recommendation_overview(result)
        render_segment_strategy_cards(result)
