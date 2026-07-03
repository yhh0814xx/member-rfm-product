"""Chinese Streamlit interface for immutable RFM pipeline outputs."""

from __future__ import annotations

import os
from pathlib import Path

import plotly.express as px
import streamlit as st

try:
    from app.dashboard_data import (
        RunDataError,
        compute_kpis,
        dataframe_to_csv_bytes,
        discover_runs,
        filter_customers,
        load_run,
    )
except ModuleNotFoundError:  # ``streamlit run app/app.py`` execution path
    from dashboard_data import (  # type: ignore[no-redef]
        RunDataError,
        compute_kpis,
        dataframe_to_csv_bytes,
        discover_runs,
        filter_customers,
        load_run,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = Path(os.environ.get("RFM_RUNS_ROOT", PROJECT_ROOT / "outputs" / "runs"))

st.set_page_config(page_title="会员 RFM 分析", page_icon="📊", layout="wide")
st.title("会员 RFM 分析看板")
st.caption("读取已完成的流水线输出；本页面不会重新计算或修改 RFM 算法与分层规则。")


@st.cache_data(show_spinner=False)
def cached_load_run(run_path: str, modified_ns: int):
    """Cache immutable artifacts while invalidating replaced development runs."""
    del modified_ns
    return load_run(Path(run_path))


try:
    run_dirs = discover_runs(RUNS_ROOT)
except RunDataError as exc:
    st.error(str(exc))
    st.info(f"请检查运行结果目录：{RUNS_ROOT}")
    st.stop()

if not run_dirs:
    st.warning("尚未发现可选择的运行结果。请先执行 RFM 流水线。")
    st.code("python run_pipeline.py --output-root outputs/runs")
    st.stop()

run_by_id = {path.name: path for path in run_dirs}
run_ids = list(run_by_id)
st.sidebar.header("结果与筛选")
selected_run_id = st.sidebar.selectbox(
    "选择 run_id",
    run_ids,
    index=0,
    help="默认选择最近修改的运行结果，可手动切换。",
)
selected_run_dir = run_by_id[selected_run_id]

try:
    bundle = cached_load_run(
        str(selected_run_dir), selected_run_dir.stat().st_mtime_ns
    )
except (RunDataError, OSError) as exc:
    st.error(f"无法展示 run_id“{selected_run_id}”：{exc}")
    st.info("请选择其他 run_id，或重新运行流水线以生成完整输出。")
    st.stop()

segment_options = sorted(bundle.rfm_customers["Segment"].dropna().astype(str).unique())
selected_segments = st.sidebar.multiselect("Segment 筛选", segment_options)
customer_query = st.sidebar.text_input("CustomerID 查询", placeholder="输入完整或部分 ID")
filtered_customers = filter_customers(
    bundle.rfm_customers, selected_segments, customer_query
)

st.sidebar.caption(f"当前 run_id：{bundle.run_id}")
completed_at = bundle.metadata.get("completed_at_utc")
if completed_at:
    st.sidebar.caption(f"完成时间（UTC）：{completed_at}")

kpis = compute_kpis(bundle.rfm_customers)
kpi_columns = st.columns(4)
kpi_columns[0].metric("客户数", f"{kpis['customers']:,}")
kpi_columns[1].metric("总 Monetary", f"£{kpis['monetary']:,.2f}")
kpi_columns[2].metric("平均 Frequency", f"{kpis['average_frequency']:,.2f}")
kpi_columns[3].metric("分层数", f"{kpis['segments']:,}")

st.divider()
st.subheader("RFM 客户与分层")
left, right = st.columns(2)
with left:
    st.markdown("##### 客户表")
    st.caption(f"筛选结果：{len(filtered_customers):,} 条")
    st.dataframe(filtered_customers, width="stretch", hide_index=True)
    st.download_button(
        "下载筛选后的 RFM 客户 CSV",
        dataframe_to_csv_bytes(filtered_customers),
        file_name=f"{bundle.run_id}_rfm_customers_filtered.csv",
        mime="text/csv",
    )
with right:
    summary = bundle.segment_summary
    if selected_segments:
        summary = summary[summary["Segment"].astype(str).isin(selected_segments)]
    st.markdown("##### 分层汇总")
    st.dataframe(summary, width="stretch", hide_index=True)
    st.download_button(
        "下载分层汇总 CSV",
        dataframe_to_csv_bytes(summary),
        file_name=f"{bundle.run_id}_segment_summary.csv",
        mime="text/csv",
    )

st.divider()
st.subheader("K-Means 与算法比较")
chart_left, chart_right = st.columns(2)
with chart_left:
    kmeans_long = bundle.kmeans_evaluation.melt(
        id_vars="k",
        value_vars=["silhouette", "davies_bouldin"],
        var_name="指标",
        value_name="数值",
    )
    fig_kmeans = px.line(
        kmeans_long,
        x="k",
        y="数值",
        color="指标",
        markers=True,
        title="不同 K 值的聚类指标",
    )
    st.plotly_chart(fig_kmeans, width="stretch")
    st.dataframe(bundle.kmeans_evaluation, width="stretch", hide_index=True)
    st.download_button(
        "下载 K-Means 评估 CSV",
        dataframe_to_csv_bytes(bundle.kmeans_evaluation),
        file_name=f"{bundle.run_id}_kmeans_evaluation.csv",
        mime="text/csv",
    )
with chart_right:
    algorithms = bundle.algorithm_comparison.copy()
    algorithms["方案"] = algorithms["algorithm"].astype(str) + " / " + algorithms[
        "transform"
    ].astype(str)
    algorithm_long = algorithms.melt(
        id_vars="方案",
        value_vars=["silhouette", "davies_bouldin"],
        var_name="指标",
        value_name="数值",
    )
    fig_algorithms = px.bar(
        algorithm_long,
        x="方案",
        y="数值",
        color="指标",
        barmode="group",
        title="算法与预处理方案比较",
    )
    st.plotly_chart(fig_algorithms, width="stretch")
    st.dataframe(bundle.algorithm_comparison, width="stretch", hide_index=True)
    st.download_button(
        "下载算法比较 CSV",
        dataframe_to_csv_bytes(bundle.algorithm_comparison),
        file_name=f"{bundle.run_id}_algorithm_comparison.csv",
        mime="text/csv",
    )

st.divider()
st.subheader("分析图片")
image_columns = st.columns(2)
for index, image_path in enumerate(bundle.images):
    image_columns[index % 2].image(
        str(image_path), caption=image_path.stem, width="stretch"
    )

st.divider()
st.subheader("运行元数据")
st.json(bundle.metadata)
st.download_button(
    "下载运行元数据 JSON",
    bundle.metadata_bytes,
    file_name=f"{bundle.run_id}_run_metadata.json",
    mime="application/json",
)
st.caption(
    "界面布局与交互方式参考 Data-Storytelling-Dashboard；数据、算法和输出均来自本项目。"
)
