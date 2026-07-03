"""Streamlit page smoke tests using only temporary local artifacts."""

from __future__ import annotations

import ast
from pathlib import Path

from streamlit.testing.v1 import AppTest

from tests.test_dashboard_data import make_run


APP_PATH = Path(__file__).resolve().parents[1] / "app" / "app.py"


def test_dashboard_page_smoke(monkeypatch, tmp_path):
    make_run(tmp_path, "smoke_run")
    monkeypatch.setenv("RFM_RUNS_ROOT", str(tmp_path))
    app = AppTest.from_file(str(APP_PATH), default_timeout=15).run()

    assert not app.exception
    run_selectors = [widget for widget in app.selectbox if widget.label == "选择 run_id"]
    titles = [title for title in app.title if title.value == "会员与交易分析看板"]
    assert len(run_selectors) == 1
    assert run_selectors[0].value == "smoke_run"
    assert len(titles) == 1
    assert len(app.tabs) == 8
    assert len(app.metric) == 9
    assert any("筛选结果 4 条" in caption.value for caption in app.caption)

    app.run()
    assert not app.exception
    assert len([widget for widget in app.selectbox if widget.label == "选择 run_id"]) == 1
    assert len([title for title in app.title if title.value == "会员与交易分析看板"]) == 1


def test_dashboard_missing_transaction_tables_keeps_rfm_available(
    monkeypatch, tmp_path
):
    make_run(tmp_path, "rfm_only", include_transactions=False)
    monkeypatch.setenv("RFM_RUNS_ROOT", str(tmp_path))
    app = AppTest.from_file(str(APP_PATH), default_timeout=15).run()

    assert not app.exception
    assert len(app.metric) == 4
    assert any("交易分析不可用" in warning.value for warning in app.warning)


def test_dashboard_empty_runs_message(monkeypatch, tmp_path):
    monkeypatch.setenv("RFM_RUNS_ROOT", str(tmp_path))
    app = AppTest.from_file(str(APP_PATH), default_timeout=15).run()

    assert not app.exception
    assert any("尚未发现" in warning.value for warning in app.warning)


def test_dashboard_main_repeated_call_renders_only_once(monkeypatch, tmp_path):
    make_run(tmp_path, "single_render")
    source = f"""
import os
os.environ["RFM_RUNS_ROOT"] = r"{tmp_path}"
from app import app as dashboard
dashboard.main()
dashboard.main()
"""
    app = AppTest.from_string(source, default_timeout=15).run()

    assert not app.exception
    assert len([title for title in app.title if title.value == "会员与交易分析看板"]) == 1
    assert len([widget for widget in app.selectbox if widget.label == "选择 run_id"]) == 1
    assert "DuplicateElementId" not in str(app)
    assert "DuplicateElementKey" not in str(app)


def test_all_interactive_controls_have_stable_keys():
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    interactive = {
        "selectbox",
        "multiselect",
        "text_input",
        "date_input",
        "number_input",
        "download_button",
    }
    missing = []
    keys = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in interactive:
            continue
        key = next((kw.value for kw in node.keywords if kw.arg == "key"), None)
        if key is None:
            missing.append((node.lineno, node.func.attr))
        elif isinstance(key, ast.Constant):
            keys.append(key.value)

    assert missing == []
    assert len(keys) == len(set(keys))
