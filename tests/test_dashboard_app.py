"""Streamlit page smoke tests using only temporary local artifacts."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from tests.test_dashboard_data import make_run


APP_PATH = Path(__file__).resolve().parents[1] / "app" / "app.py"


def test_dashboard_page_smoke(monkeypatch, tmp_path):
    make_run(tmp_path, "smoke_run")
    monkeypatch.setenv("RFM_RUNS_ROOT", str(tmp_path))
    app = AppTest.from_file(str(APP_PATH), default_timeout=15).run()

    assert not app.exception
    assert app.selectbox[0].value == "smoke_run"
    assert any("会员 RFM 分析看板" in title.value for title in app.title)
    assert len(app.metric) == 4


def test_dashboard_empty_runs_message(monkeypatch, tmp_path):
    monkeypatch.setenv("RFM_RUNS_ROOT", str(tmp_path))
    app = AppTest.from_file(str(APP_PATH), default_timeout=15).run()

    assert not app.exception
    assert any("尚未发现" in warning.value for warning in app.warning)
