"""Streamlit tests for the member-operation workbench."""

from __future__ import annotations

import ast
from pathlib import Path

from streamlit.testing.v1 import AppTest

from tests.test_dashboard_data import make_run


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VIEW_PATH = PROJECT_ROOT / "app" / "recommendations_view.py"


def view_source(run_dir: Path, config_path: Path | None = None) -> str:
    config_argument = f", config_path=r'{config_path}'" if config_path else ""
    return f"""
from pathlib import Path
from app.dashboard_data import load_run
from app.recommendations_view import render_recommendations
bundle = load_run(Path(r"{run_dir}"))
render_recommendations(bundle{config_argument})
"""


def test_recommendations_page_renders_workbench_tabs_and_downloads(tmp_path):
    app = AppTest.from_string(
        view_source(make_run(tmp_path, "recommendation_run")), default_timeout=20
    ).run()
    assert not app.exception
    assert any("会员运营工作台" in item.value for item in app.subheader)
    assert any(tab.label == "今日待办" for tab in app.tabs)
    assert any(tab.label == "客户详情与话术" for tab in app.tabs)
    assert any(tab.label == "分层分析" for tab in app.tabs)
    assert any(item.label == "待联系客户数" for item in app.metric)
    assert any(item.label == "立即处理客户数" for item in app.metric)
    assert any(item.label == "下载当前客户行动名单CSV" for item in app.get("download_button"))
    assert any("客户行动队列" in item.value for item in app.markdown)
    assert any("客户价值-流失风险矩阵" in item.value for item in app.markdown)


def test_recommendations_page_missing_config_shows_chinese_error(tmp_path):
    run_dir = make_run(tmp_path, "missing_config")
    app = AppTest.from_string(
        view_source(run_dir, tmp_path / "does-not-exist.json"), default_timeout=20
    ).run()
    assert not app.exception
    assert any("缺少会员运营建议配置文件" in item.value for item in app.error)


def test_recommendations_page_rerun_has_no_duplicate_widgets(tmp_path):
    app = AppTest.from_string(
        view_source(make_run(tmp_path, "rerun")), default_timeout=20
    ).run()
    app.run()
    assert not app.exception
    rendered = str(app)
    assert "DuplicateElementId" not in rendered
    assert "DuplicateElementKey" not in rendered


def test_recommendation_view_interactive_controls_have_unique_keys():
    tree = ast.parse(VIEW_PATH.read_text(encoding="utf-8"))
    interactive = {"selectbox", "multiselect", "text_input", "button", "download_button", "text_area"}
    keys = []
    missing = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in interactive:
            continue
        key = next((keyword.value for keyword in node.keywords if keyword.arg == "key"), None)
        if key is None:
            missing.append((node.lineno, node.func.attr))
        elif isinstance(key, ast.Constant):
            keys.append(key.value)
    assert missing == []
    assert len(keys) == len(set(keys))


def test_rendered_page_has_no_reference_specific_residue(tmp_path):
    app = AppTest.from_string(
        view_source(make_run(tmp_path, "clean_copy")), default_timeout=20
    ).run()
    visible_values = []
    for element_type in (
        "subheader",
        "markdown",
        "caption",
        "info",
        "warning",
        "error",
        "expander",
    ):
        for item in app.get(element_type):
            value = getattr(item, "value", None) or getattr(item, "label", "")
            visible_values.append(str(value))
    rendered = "\n".join(visible_values).lower()
    for forbidden in ("amazon", "prime day", "klaviyo", "$", "fixed clv", "流失概率", "ai预测", "转化概率"):
        assert forbidden not in rendered


def test_action_queue_segment_filter_updates_customer_table(tmp_path):
    app = AppTest.from_string(
        view_source(make_run(tmp_path, "target_selection")), default_timeout=20
    ).run()
    segment_filter = next(
        item for item in app.multiselect if item.label == "Segment" and item.key == "workbench_segment_filter"
    )
    segment_filter.set_value(["At Risk"])
    app.run()
    assert not app.exception
    queues = [
        item.value
        for item in app.dataframe
        if "MessageEntry" in getattr(item.value, "columns", [])
    ]
    assert len(queues) == 1
    assert queues[0]["CustomerID"].tolist() == ["1002"]
    assert queues[0]["Segment"].unique().tolist() == ["At Risk"]


def test_empty_recommendation_scope_does_not_crash(tmp_path):
    source = f"""
from pathlib import Path
from app.dashboard_data import load_run
from app.recommendations_view import render_recommendations
bundle = load_run(Path(r"{make_run(tmp_path, 'empty_scope')}"))
empty = bundle.rfm_customers.iloc[0:0]
render_recommendations(bundle, rfm_customers=empty, segment_summary=bundle.segment_summary.iloc[0:0])
"""
    app = AppTest.from_string(source, default_timeout=20).run()
    assert not app.exception
    assert any("没有待运营客户" in item.value for item in app.info)
