"""Streamlit tests for the run-scoped member-operation page."""

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


def test_recommendations_page_renders_ten_cards_and_downloads(tmp_path):
    app = AppTest.from_string(
        view_source(make_run(tmp_path, "recommendation_run")), default_timeout=20
    ).run()
    assert not app.exception
    assert len(app.expander) == 10
    assert any("会员运营建议" in item.value for item in app.subheader)
    assert any(item.label == "选择目标会员分层" for item in app.selectbox)
    assert len(app.get("download_button")) == 2
    assert any("商家行动总览" in item.value for item in app.markdown)


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
    interactive = {"selectbox", "multiselect", "download_button"}
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
    for forbidden in ("amazon", "prime day", "klaviyo", "$", "fixed clv"):
        assert forbidden not in rendered


def test_target_segment_selection_updates_customer_table(tmp_path):
    app = AppTest.from_string(
        view_source(make_run(tmp_path, "target_selection")), default_timeout=20
    ).run()
    selector = next(item for item in app.selectbox if item.label == "选择目标会员分层")
    selector.set_value("At Risk")
    app.run()
    assert not app.exception
    targets = [
        item.value
        for item in app.dataframe
        if "推荐运营任务" in getattr(item.value, "columns", [])
    ]
    assert len(targets) == 1
    assert targets[0]["CustomerID"].tolist() == ["1002"]
    assert targets[0]["Segment"].unique().tolist() == ["At Risk"]
