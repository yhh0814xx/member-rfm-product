"""Streamlit page smoke tests using only temporary local artifacts."""

from __future__ import annotations

import ast
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from streamlit.testing.v1 import AppTest

from tests.test_dashboard_data import make_run


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_ROOT / "streamlit_app.py"
APP_MODULE_PATH = PROJECT_ROOT / "app" / "app.py"
RUN_DASHBOARD_PATH = PROJECT_ROOT / "run_dashboard.py"


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
    assert len(app.tabs) == 13
    assert any(tab.label == "数据上传与分析" for tab in app.tabs)
    assert any(tab.label == "会员运营建议" for tab in app.tabs)
    assert len(app.metric) >= 17
    assert any("筛选结果 3 条" in caption.value for caption in app.caption)

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
    assert any(metric.label == "客户数" for metric in app.metric)
    assert any("会员运营工作台" in item.value for item in app.subheader)
    assert any("交易分析不可用" in warning.value for warning in app.warning)


def test_dashboard_empty_runs_message(monkeypatch, tmp_path):
    monkeypatch.setenv("RFM_RUNS_ROOT", str(tmp_path))
    app = AppTest.from_file(str(APP_PATH), default_timeout=15).run()

    assert not app.exception
    assert any("尚未发现" in warning.value for warning in app.warning)


def test_completed_upload_pending_run_is_selected(monkeypatch, tmp_path):
    make_run(tmp_path, "current_run")
    make_run(tmp_path, "uploaded_run")
    monkeypatch.setenv("RFM_RUNS_ROOT", str(tmp_path))
    app = AppTest.from_file(str(APP_PATH), default_timeout=15)
    app.session_state["_pending_run_id"] = "uploaded_run"
    app.run()

    assert not app.exception
    selector = next(item for item in app.selectbox if item.label == "选择 run_id")
    assert selector.value == "uploaded_run"
    assert "_pending_run_id" not in app.session_state


def test_country_filter_updates_transaction_rfm_and_recommendation_views(
    monkeypatch, tmp_path
):
    make_run(tmp_path, "country_filter")
    monkeypatch.setenv("RFM_RUNS_ROOT", str(tmp_path))
    app = AppTest.from_file(str(APP_PATH), default_timeout=20).run()
    country = next(item for item in app.multiselect if item.label == "国家")
    country.set_value(["France"])
    app.run()

    assert not app.exception
    assert any("筛选后交易：1" in item.value for item in app.caption)
    assert any("筛选结果 1 条" in item.value for item in app.caption)
    assert any("筛选结果：1 条" in item.value for item in app.caption)
    assert any(
        item.label == "当前筛选客户数" and item.value == "1"
        for item in app.metric
    )
    targets = [
        item.value
        for item in app.dataframe
        if "MessageEntry" in getattr(item.value, "columns", [])
    ]
    assert len(targets) == 1
    assert targets[0]["Segment"].tolist() == ["At Risk"]


def test_reset_global_filters_restores_complete_display_scope(monkeypatch, tmp_path):
    make_run(tmp_path, "reset_filters")
    monkeypatch.setenv("RFM_RUNS_ROOT", str(tmp_path))
    app = AppTest.from_file(str(APP_PATH), default_timeout=20).run()
    country = next(item for item in app.multiselect if item.label == "国家")
    country.set_value(["France"])
    app.run()
    assert any("筛选后交易：1" in item.value for item in app.caption)

    reset = next(item for item in app.button if item.label == "重置全部筛选")
    reset.click()
    app.run()
    country = next(item for item in app.multiselect if item.label == "国家")
    assert country.value == []
    assert any("筛选后交易：3" in item.value for item in app.caption)


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
    tree = ast.parse(APP_MODULE_PATH.read_text(encoding="utf-8"))
    interactive = {
        "selectbox",
        "multiselect",
        "text_input",
        "date_input",
        "number_input",
        "file_uploader",
        "button",
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


def test_run_dashboard_real_entry_has_page_without_streamlit_errors(
    monkeypatch, tmp_path
):
    make_run(tmp_path, "real_entry")
    monkeypatch.setenv("RFM_RUNS_ROOT", str(tmp_path))
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    command = [
        sys.executable,
        str(RUN_DASHBOARD_PATH),
        "--server.address",
        "127.0.0.1",
        "--server.port",
        str(port),
        "--browser.gatherUsageStats",
        "false",
    ]
    process = subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        env=os.environ.copy(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=os.name != "nt",
        creationflags=(
            subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        ),
    )
    output = ""
    try:
        deadline = time.time() + 30
        while time.time() < deadline:
            if process.poll() is not None:
                output = process.communicate(timeout=5)[0]
                raise AssertionError(f"Streamlit提前退出：{output}")
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/_stcore/health", timeout=1
                ) as response:
                    if response.status == 200 and response.read() == b"ok":
                        break
            except OSError:
                time.sleep(0.2)
        else:
            raise AssertionError("run_dashboard.py启动超时")

        app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
        assert not app.exception
        assert len(app.tabs) == 13
        assert len(app.file_uploader) == 1
        app.run()
        assert not app.exception
    finally:
        if process.poll() is None:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    check=False,
                )
            else:
                os.killpg(process.pid, signal.SIGTERM)
        try:
            remaining = process.communicate(timeout=10)[0]
            output += remaining
        except subprocess.TimeoutExpired:
            process.kill()

    assert "ModuleNotFoundError" not in output
    assert "StreamlitDuplicateElement" not in output
