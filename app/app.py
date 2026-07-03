"""Chinese Streamlit interface for immutable RFM and transaction outputs."""

from __future__ import annotations

import hashlib
import math
import os
import sys
from pathlib import Path

import plotly.express as px
import streamlit as st
from streamlit.runtime.scriptrunner import get_script_run_ctx

from .dashboard_data import (
    RunDataError,
    compute_kpis,
    compute_transaction_kpis,
    dataframe_to_csv_bytes,
    discover_runs,
    filter_customers,
    filter_transactions,
    load_run,
    load_transaction_tables,
    product_key,
    summarize_filtered_countries,
    summarize_filtered_monthly,
    summarize_filtered_products,
)
from .upload_analysis import (
    AnalysisExecutionError,
    generate_upload_run_id,
    run_uploaded_analysis,
    validate_upload,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = Path(os.environ.get("RFM_RUNS_ROOT", PROJECT_ROOT / "outputs" / "runs"))

@st.cache_data(show_spinner=False)
def cached_load_run(run_path: str, modified_ns: int):
    """Cache immutable core artifacts while invalidating replaced runs."""
    del modified_ns
    return load_run(Path(run_path))


@st.cache_data(show_spinner="正在缓存交易分析数据……")
def cached_load_transaction_tables(run_path: str, modified_ns: int):
    """Cache the large transaction snapshot and its exported summaries."""
    del modified_ns
    return load_transaction_tables(Path(run_path))


@st.cache_data(show_spinner=False)
def cached_validate_upload(filename: str, content: bytes):
    """Cache validation by filename and file content hash."""
    return validate_upload(filename, content)


_RENDER_MARKER = "__member_rfm_dashboard_rendered__"
_bare_main_invoked = False


def main():
    """Render once per Streamlit run while allowing normal reruns."""
    global _bare_main_invoked, RUNS_ROOT
    context = get_script_run_ctx(suppress_warning=True)
    if context is None:
        if _bare_main_invoked:
            return
        _bare_main_invoked = True
    else:
        if not context.widget_user_keys_this_run.check_and_add(_RENDER_MARKER):
            return

    RUNS_ROOT = Path(
        os.environ.get("RFM_RUNS_ROOT", PROJECT_ROOT / "outputs" / "runs")
    )

    st.set_page_config(page_title="会员与交易分析", page_icon="📊", layout="wide")
    st.title("会员与交易分析看板")
    st.caption("读取已完成的流水线输出；页面不会重新计算或修改任何分析算法。")

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
    pending_run_id = st.session_state.pop("_pending_run_id", None)
    if pending_run_id in run_by_id:
        st.session_state["run_id_selector"] = pending_run_id
    st.sidebar.header("结果与全局筛选")
    selected_run_id = st.sidebar.selectbox(
        "选择 run_id",
        list(run_by_id),
        index=0,
        help="默认选择最近修改的运行结果，可手动切换。",
        key="run_id_selector",
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

    transaction_bundle = None
    transaction_error = None
    try:
        transaction_bundle = cached_load_transaction_tables(
            str(selected_run_dir), selected_run_dir.stat().st_mtime_ns
        )
    except (RunDataError, OSError) as exc:
        transaction_error = str(exc)

    segment_options = sorted(bundle.rfm_customers["Segment"].dropna().astype(str).unique())
    selected_segments = st.sidebar.multiselect(
        "RFM Segment", segment_options, key="rfm_segment_filter"
    )
    customer_query = st.sidebar.text_input(
        "RFM CustomerID",
        placeholder="输入完整或部分客户ID",
        key="rfm_customer_query",
    )
    filtered_customers = filter_customers(
        bundle.rfm_customers, selected_segments, customer_query
    )

    filtered_transactions = None
    selected_date_range = None
    selected_countries: list[str] = []
    selected_products: list[str] = []
    transaction_query = ""
    if transaction_bundle is not None:
        transactions = transaction_bundle.transactions
        min_date = transactions["InvoiceDate"].min().date()
        max_date = transactions["InvoiceDate"].max().date()
        selected_date_range = st.sidebar.date_input(
            "交易日期",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date,
            key="transaction_date_filter",
        )
        country_options = sorted(transactions["Country"].dropna().astype(str).unique())
        selected_countries = st.sidebar.multiselect(
            "国家", country_options, key="transaction_country_filter"
        )
        product_options = sorted(
            product_key(transaction_bundle.product_summary).drop_duplicates().tolist()
        )
        selected_products = st.sidebar.multiselect(
            "商品（编码 | 描述）",
            product_options,
            key="transaction_product_filter",
        )
        transaction_query = st.sidebar.text_input(
            "交易查询",
            placeholder="订单、客户、商品编码或描述",
            key="transaction_query",
        )
        filtered_transactions = filter_transactions(
            transactions,
            tuple(selected_date_range) if len(selected_date_range) == 2 else None,
            selected_countries,
            selected_products,
            transaction_query,
        )

    st.sidebar.caption(f"当前 run_id：{bundle.run_id}")
    completed_at = bundle.metadata.get("completed_at_utc")
    if completed_at:
        st.sidebar.caption(f"完成时间（UTC）：{completed_at}")

    tab_names = [
        "数据上传与分析",
        "经营总览",
        "月度趋势",
        "国家分析",
        "商品分析",
        "Cohort留存",
        "交易明细",
        "RFM与聚类",
        "下载中心",
    ]
    (
        upload_tab,
        overview_tab,
        monthly_tab,
        country_tab,
        product_tab,
        cohort_tab,
        transaction_tab,
        rfm_tab,
        download_tab,
    ) = st.tabs(tab_names)

    with upload_tab:
        st.subheader("数据上传、校验与一键分析")
        st.caption(
            "支持CSV和XLSX。上传后仅执行校验；确认通过并点击按钮后，才会运行现有pipeline。"
        )
        st.info(
            "数据规则提示：InvoiceNo以C开头会按取消订单删除；如果所有交易日期完全相同，"
            "系统会在分析前阻止运行，因为无法计算有效的RFM Recency五分位。"
        )
        uploaded_file = st.file_uploader(
            "上传会员交易文件",
            type=["csv", "xlsx"],
            accept_multiple_files=False,
            key="transaction_upload_file",
        )
        if uploaded_file is None:
            st.info("请选择CSV或XLSX文件开始校验。")
        else:
            content = uploaded_file.getvalue()
            with st.status("校验中……", expanded=True) as validation_status:
                validation = cached_validate_upload(uploaded_file.name, content)
                if validation.can_analyze:
                    validation_status.update(
                        label="校验完成，可以开始分析", state="complete"
                    )
                else:
                    validation_status.update(
                        label="校验完成，存在阻断性错误", state="error"
                    )

            metrics = st.columns(4)
            metrics[0].metric("文件大小", f"{validation.file_size / 1024 / 1024:.2f} MiB")
            metrics[1].metric("文件行数", f"{validation.total_rows:,}")
            metrics[2].metric("可处理行数", f"{validation.processable_rows:,}")
            metrics[3].metric("可处理客户", f"{validation.processable_customers:,}")

            st.markdown("##### 数据预览（最多50行）")
            st.dataframe(validation.preview, width="stretch", hide_index=True)
            st.markdown("##### 校验结果")
            for message in validation.errors:
                st.error(message)
            for message in validation.warnings:
                st.warning(message)
            if validation.can_analyze:
                st.success("校验通过：允许开始分析。")
            else:
                st.error("校验未通过：一键分析按钮已禁用。")

            digest = hashlib.sha256(content).hexdigest()
            already_analyzed = st.session_state.get("_last_upload_digest") == digest
            in_progress = bool(st.session_state.get("_analysis_in_progress", False))
            if already_analyzed:
                st.info(
                    f"该文件已生成run_id：{st.session_state.get('_last_upload_run_id')}，"
                    "为防止重复运行，按钮已禁用。"
                )
            start_analysis = st.button(
                "一键分析",
                type="primary",
                disabled=(
                    not validation.can_analyze or in_progress or already_analyzed
                ),
                key="start_uploaded_analysis",
            )
            if start_analysis:
                st.session_state["_analysis_in_progress"] = True
                selected_upload_run_id = generate_upload_run_id(RUNS_ROOT)
                with st.status("分析中……", expanded=True) as analysis_status:
                    analysis_status.write(
                        f"正在调用现有pipeline，run_id：{selected_upload_run_id}"
                    )
                    try:
                        venv_python = (
                            Path(sys.prefix) / "Scripts" / "python.exe"
                            if os.name == "nt"
                            else Path(sys.prefix) / "bin" / "python"
                        )
                        if not venv_python.is_file():
                            venv_python = Path(sys.executable)
                        result = run_uploaded_analysis(
                            validation.cleaned_data,
                            PROJECT_ROOT,
                            RUNS_ROOT,
                            run_id=selected_upload_run_id,
                            python_executable=venv_python,
                        )
                    except AnalysisExecutionError as exc:
                        analysis_status.update(label="分析失败", state="error")
                        st.error(str(exc))
                    else:
                        analysis_status.update(label="分析完成", state="complete")
                        st.success(f"分析完成：{result.run_id}")
                        st.session_state["_last_upload_digest"] = digest
                        st.session_state["_last_upload_run_id"] = result.run_id
                        st.session_state["_pending_run_id"] = result.run_id
                        st.session_state["_analysis_in_progress"] = False
                        st.rerun()
                    finally:
                        st.session_state["_analysis_in_progress"] = False

    with overview_tab:
        st.subheader("经营总览")
        if filtered_transactions is None:
            st.warning(f"交易分析不可用：{transaction_error}。RFM与聚类仍可正常使用。")
        else:
            transaction_kpis = compute_transaction_kpis(filtered_transactions)
            columns = st.columns(5)
            columns[0].metric("Revenue", f"£{transaction_kpis['revenue']:,.2f}")
            columns[1].metric("Orders", f"{transaction_kpis['orders']:,}")
            columns[2].metric("Customers", f"{transaction_kpis['customers']:,}")
            columns[3].metric("AOV", f"£{transaction_kpis['average_order_value']:,.2f}")
            columns[4].metric("Quantity", f"{transaction_kpis['quantity']:,.0f}")
            st.caption(f"当前筛选包含 {len(filtered_transactions):,} 条交易记录。")

    with monthly_tab:
        st.subheader("月度趋势")
        if filtered_transactions is None:
            st.info(f"无法展示月度趋势：{transaction_error}")
        else:
            monthly = summarize_filtered_monthly(filtered_transactions)
            if monthly.empty:
                st.info("当前筛选条件下没有月度数据。")
            else:
                st.plotly_chart(
                    px.line(
                        monthly,
                        x="Month",
                        y="Revenue",
                        markers=True,
                        title="月度销售额",
                        labels={"Revenue": "销售额", "Month": "月份"},
                    ),
                    width="stretch",
                )
                volume = monthly.melt(
                    id_vars="Month",
                    value_vars=["Orders", "Customers"],
                    var_name="指标",
                    value_name="数量",
                )
                st.plotly_chart(
                    px.line(
                        volume,
                        x="Month",
                        y="数量",
                        color="指标",
                        markers=True,
                        title="月度订单数与客户数",
                    ),
                    width="stretch",
                )

    with country_tab:
        st.subheader("国家分析")
        if filtered_transactions is None:
            st.info(f"无法展示国家分析：{transaction_error}")
        else:
            countries = summarize_filtered_countries(filtered_transactions)
            if countries.empty:
                st.info("当前筛选条件下没有国家数据。")
            else:
                left, right = st.columns(2)
                left.plotly_chart(
                    px.pie(
                        countries,
                        values="Revenue",
                        names="Country",
                        title="国家销售贡献",
                        hole=0.4,
                    ),
                    width="stretch",
                )
                top_countries = countries.head(20).sort_values("Revenue")
                right.plotly_chart(
                    px.bar(
                        top_countries,
                        x="Revenue",
                        y="Country",
                        orientation="h",
                        title="国家销售额排行（前20）",
                    ),
                    width="stretch",
                )
                st.dataframe(countries, width="stretch", hide_index=True)

    with product_tab:
        st.subheader("商品分析")
        if filtered_transactions is None:
            st.info(f"无法展示商品分析：{transaction_error}")
        else:
            products = summarize_filtered_products(filtered_transactions)
            if products.empty:
                st.info("当前筛选条件下没有商品数据。")
            else:
                top_n = st.selectbox(
                    "排行数量", [10, 20, 50], index=1, key="product_top_n"
                )
                products = products.assign(商品=product_key(products))
                left, right = st.columns(2)
                top_revenue = products.nlargest(top_n, "Revenue").sort_values("Revenue")
                left.plotly_chart(
                    px.bar(
                        top_revenue,
                        x="Revenue",
                        y="商品",
                        orientation="h",
                        title=f"商品销售额排行（前{top_n}）",
                    ),
                    width="stretch",
                )
                top_quantity = products.nlargest(top_n, "Quantity").sort_values("Quantity")
                right.plotly_chart(
                    px.bar(
                        top_quantity,
                        x="Quantity",
                        y="商品",
                        orientation="h",
                        title=f"商品销量排行（前{top_n}）",
                    ),
                    width="stretch",
                )
                st.dataframe(
                    products.drop(columns="商品"), width="stretch", hide_index=True
                )

    with cohort_tab:
        st.subheader("Cohort留存")
        if transaction_bundle is None:
            st.info(f"无法展示Cohort留存：{transaction_error}")
        else:
            retention = transaction_bundle.cohort_retention
            heatmap = retention.pivot(
                index="CohortMonth", columns="Period", values="RetentionRate"
            )
            st.plotly_chart(
                px.imshow(
                    heatmap,
                    zmin=0,
                    zmax=1,
                    color_continuous_scale="Blues",
                    aspect="auto",
                    text_auto=".0%",
                    labels={"x": "Period", "y": "CohortMonth", "color": "留存率"},
                    title="月度客户留存率",
                ),
                width="stretch",
            )
            st.caption(
                "热力图直接读取 cohort_retention.csv；缺失期保持为空，不补0，也不根据交易筛选重新计算。"
            )

    with transaction_tab:
        st.subheader("交易明细")
        if filtered_transactions is None:
            st.info(f"无法展示交易明细：{transaction_error}")
        else:
            page_size = st.selectbox(
                "每页行数", [50, 100, 200], index=1, key="transaction_page_size"
            )
            total_rows = len(filtered_transactions)
            total_pages = max(1, math.ceil(total_rows / page_size))
            page = int(
                st.number_input(
                    "页码",
                    min_value=1,
                    max_value=total_pages,
                    value=1,
                    step=1,
                    key="transaction_page_number",
                )
            )
            start = (page - 1) * page_size
            page_frame = filtered_transactions.iloc[start : start + page_size]
            st.caption(
                f"筛选结果 {total_rows:,} 条；第 {page}/{total_pages} 页，页面最多展示 {page_size} 条。"
            )
            st.dataframe(page_frame, width="stretch", hide_index=True)
            st.download_button(
                "下载完整筛选结果 CSV",
                dataframe_to_csv_bytes(filtered_transactions),
                file_name=f"{bundle.run_id}_transactions_filtered.csv",
                mime="text/csv",
                key="download_filtered_transactions",
            )

    with rfm_tab:
        st.subheader("RFM客户与聚类")
        rfm_kpis = compute_kpis(bundle.rfm_customers)
        columns = st.columns(4)
        columns[0].metric("客户数", f"{rfm_kpis['customers']:,}")
        columns[1].metric("总 Monetary", f"£{rfm_kpis['monetary']:,.2f}")
        columns[2].metric("平均 Frequency", f"{rfm_kpis['average_frequency']:,.2f}")
        columns[3].metric("分层数", f"{rfm_kpis['segments']:,}")

        left, right = st.columns(2)
        with left:
            st.markdown("##### RFM客户表")
            st.caption(f"筛选结果：{len(filtered_customers):,} 条")
            st.dataframe(filtered_customers, width="stretch", hide_index=True)
            st.download_button(
                "下载筛选后的RFM客户CSV",
                dataframe_to_csv_bytes(filtered_customers),
                file_name=f"{bundle.run_id}_rfm_customers_filtered.csv",
                mime="text/csv",
                key="download_filtered_rfm_customers",
            )
        with right:
            summary = bundle.segment_summary
            if selected_segments:
                summary = summary[summary["Segment"].astype(str).isin(selected_segments)]
            st.markdown("##### 分层汇总")
            st.dataframe(summary, width="stretch", hide_index=True)

        chart_left, chart_right = st.columns(2)
        with chart_left:
            kmeans_long = bundle.kmeans_evaluation.melt(
                id_vars="k",
                value_vars=["silhouette", "davies_bouldin"],
                var_name="指标",
                value_name="数值",
            )
            st.plotly_chart(
                px.line(
                    kmeans_long,
                    x="k",
                    y="数值",
                    color="指标",
                    markers=True,
                    title="不同K值的聚类指标",
                ),
                width="stretch",
            )
            st.dataframe(bundle.kmeans_evaluation, width="stretch", hide_index=True)
        with chart_right:
            algorithms = bundle.algorithm_comparison.copy()
            algorithms["方案"] = (
                algorithms["algorithm"].astype(str)
                + " / "
                + algorithms["transform"].astype(str)
            )
            algorithm_long = algorithms.melt(
                id_vars="方案",
                value_vars=["silhouette", "davies_bouldin"],
                var_name="指标",
                value_name="数值",
            )
            st.plotly_chart(
                px.bar(
                    algorithm_long,
                    x="方案",
                    y="数值",
                    color="指标",
                    barmode="group",
                    title="算法与预处理方案比较",
                ),
                width="stretch",
            )
            st.dataframe(bundle.algorithm_comparison, width="stretch", hide_index=True)

        st.markdown("#### 7张分析图片")
        image_columns = st.columns(2)
        for index, image_path in enumerate(bundle.images):
            image_columns[index % 2].image(
                str(image_path), caption=image_path.stem, width="stretch"
            )

    with download_tab:
        st.subheader("下载中心")
        st.markdown("##### RFM与聚类结果")
        rfm_downloads = [
            ("RFM客户", bundle.rfm_customers, "rfm_customers.csv"),
            ("分层汇总", bundle.segment_summary, "segment_summary.csv"),
            ("K-Means评估", bundle.kmeans_evaluation, "kmeans_evaluation.csv"),
            ("算法比较", bundle.algorithm_comparison, "algorithm_comparison.csv"),
        ]
        columns = st.columns(2)
        for index, (label, frame, filename) in enumerate(rfm_downloads):
            columns[index % 2].download_button(
                f"下载{label}CSV",
                dataframe_to_csv_bytes(frame),
                file_name=f"{bundle.run_id}_{filename}",
                mime="text/csv",
                key=f"download_{filename}",
            )

        if transaction_bundle is not None:
            st.markdown("##### 交易分析导出")
            transaction_downloads = [
                ("交易快照", transaction_bundle.transactions, "transaction_clean.csv"),
                ("月度汇总", transaction_bundle.monthly_summary, "monthly_summary.csv"),
                ("国家汇总", transaction_bundle.country_summary, "country_summary.csv"),
                ("商品汇总", transaction_bundle.product_summary, "product_summary.csv"),
                ("Cohort留存", transaction_bundle.cohort_retention, "cohort_retention.csv"),
            ]
            columns = st.columns(2)
            for index, (label, frame, filename) in enumerate(transaction_downloads):
                columns[index % 2].download_button(
                    f"下载{label}CSV",
                    dataframe_to_csv_bytes(frame),
                    file_name=f"{bundle.run_id}_{filename}",
                    mime="text/csv",
                    key=f"download_{filename}",
                )
        else:
            st.warning(f"交易分析导出不可用：{transaction_error}")

        st.markdown("##### 运行元数据")
        st.json(bundle.metadata)
        st.download_button(
            "下载运行元数据JSON",
            bundle.metadata_bytes,
            file_name=f"{bundle.run_id}_run_metadata.json",
            mime="application/json",
            key="download_run_metadata",
        )

    st.caption(
        "界面布局与交互方式参考 Data-Storytelling-Dashboard；数据、算法和输出均来自本项目。"
    )


if __name__ == "__main__":
    main()
