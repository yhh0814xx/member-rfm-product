"""Upload validation and isolated pipeline orchestration tests."""

from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from app.upload_analysis import (
    AnalysisExecutionError,
    generate_upload_run_id,
    run_uploaded_analysis,
    validate_upload,
)
from tests.test_dashboard_data import make_run


def valid_upload_frame(customers: int = 20) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "InvoiceNo": [f"I{index:04d}" for index in range(customers)],
            "StockCode": [f"P{index % 4}" for index in range(customers)],
            "Description": [f"Product {index % 4}" for index in range(customers)],
            "Quantity": [(index % 5) + 1 for index in range(customers)],
            "InvoiceDate": pd.date_range("2024-01-01", periods=customers, freq="D"),
            "UnitPrice": [10.0 + index for index in range(customers)],
            "CustomerID": [f"C{index:04d}" for index in range(customers)],
            "Country": ["UK" if index % 2 else "France" for index in range(customers)],
        }
    )


def csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False).encode("utf-8")


def test_valid_csv_is_cleaned_but_does_not_run_analysis():
    result = validate_upload("members.csv", csv_bytes(valid_upload_frame()))

    assert result.can_analyze
    assert result.total_rows == result.processable_rows == 20
    assert result.processable_customers == 20
    assert result.errors == ()
    assert "TotalAmount" in result.cleaned_data


def test_valid_xlsx_is_supported():
    stream = io.BytesIO()
    valid_upload_frame().to_excel(stream, index=False, engine="openpyxl")

    result = validate_upload("members.xlsx", stream.getvalue())

    assert result.can_analyze
    assert result.processable_rows == 20


def test_missing_columns_invalid_dates_and_numeric_values_block_analysis():
    missing = valid_upload_frame().drop(columns="Country")
    assert "缺少必需字段" in validate_upload(
        "missing.csv", csv_bytes(missing)
    ).errors[0]

    invalid = valid_upload_frame()
    invalid["InvoiceDate"] = invalid["InvoiceDate"].astype(str)
    invalid["Quantity"] = invalid["Quantity"].astype(object)
    invalid.loc[0, "InvoiceDate"] = "not-a-date"
    invalid.loc[1, "Quantity"] = "not-a-number"
    result = validate_upload("invalid.csv", csv_bytes(invalid))
    assert not result.can_analyze
    assert any("InvoiceDate" in error for error in result.errors)
    assert any("Quantity" in error for error in result.errors)


def test_identical_transaction_dates_are_blocked_before_pipeline():
    frame = valid_upload_frame()
    frame["InvoiceDate"] = "2024-01-01"

    result = validate_upload("same_dates.csv", csv_bytes(frame))

    assert not result.can_analyze
    assert any("所有交易日期完全相同" in error for error in result.errors)


def test_cleanable_issues_are_warned_and_counted():
    frame = valid_upload_frame()
    frame.loc[0, "CustomerID"] = None
    frame.loc[1, "Quantity"] = 0
    frame.loc[2, "InvoiceNo"] = "C0002"
    frame = pd.concat([frame, frame.iloc[[3]]], ignore_index=True)

    result = validate_upload("warnings.csv", csv_bytes(frame))

    assert result.can_analyze
    assert result.total_rows == 21
    assert result.processable_rows == 17
    assert result.processable_customers == 17
    assert any("CustomerID缺失" in warning for warning in result.warnings)
    assert any("精确重复" in warning for warning in result.warnings)
    assert any("非正" in warning for warning in result.warnings)
    assert any("取消订单" in warning for warning in result.warnings)


@pytest.mark.parametrize("filename", ["../escape.csv", "nested/file.xlsx", "bad.txt"])
def test_unsafe_or_unsupported_upload_name_is_rejected(filename):
    result = validate_upload(filename, csv_bytes(valid_upload_frame()))
    assert not result.can_analyze


def test_generated_upload_run_id_is_safe_and_unique(tmp_path):
    first = generate_upload_run_id(tmp_path)
    (tmp_path / first).mkdir()
    second = generate_upload_run_id(tmp_path)
    assert first.startswith("upload_")
    assert second.startswith("upload_")
    assert first != second
    assert "/" not in second and "\\" not in second


def test_successful_analysis_is_verified_and_atomically_published(
    monkeypatch, tmp_path
):
    project_root = tmp_path / "project"
    runs_root = project_root / "outputs" / "runs"
    project_root.mkdir()
    validation = validate_upload("members.csv", csv_bytes(valid_upload_frame()))
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        output_root = Path(command[command.index("--output-root") + 1])
        run_id = command[command.index("--run-id") + 1]
        make_run(output_root, run_id)
        return SimpleNamespace(returncode=0, stdout="pipeline complete", stderr="")

    monkeypatch.setattr("app.upload_analysis.subprocess.run", fake_run)
    result = run_uploaded_analysis(
        validation.cleaned_data,
        project_root,
        runs_root,
        run_id="upload_success",
        python_executable=Path("python.exe"),
    )

    assert result.run_dir == runs_root / "upload_success"
    assert result.run_dir.is_dir()
    assert captured["kwargs"]["shell"] is False
    assert isinstance(captured["command"], list)
    assert not list((project_root / "outputs" / ".staging").glob("*"))
    assert not list((project_root / "outputs" / ".locks").glob("*"))


def test_failed_analysis_rolls_back_and_writes_chinese_report(monkeypatch, tmp_path):
    project_root = tmp_path / "project"
    runs_root = project_root / "outputs" / "runs"
    project_root.mkdir()
    validation = validate_upload("members.csv", csv_bytes(valid_upload_frame()))

    monkeypatch.setattr(
        "app.upload_analysis.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=2, stdout="", stderr="deliberate failure"
        ),
    )
    with pytest.raises(AnalysisExecutionError) as caught:
        run_uploaded_analysis(
            validation.cleaned_data,
            project_root,
            runs_root,
            run_id="upload_failure",
            python_executable=Path("python.exe"),
        )

    assert not (runs_root / "upload_failure").exists()
    assert not list((project_root / "outputs" / ".staging").glob("*"))
    report = json.loads(caught.value.report_path.read_text(encoding="utf-8"))
    assert report["状态"] == "失败"
    assert report["run_id"] == "upload_failure"
    assert "pipeline" in report["失败阶段"]


def test_existing_run_is_never_overwritten(tmp_path):
    project_root = tmp_path / "project"
    runs_root = project_root / "outputs" / "runs"
    existing = runs_root / "upload_existing"
    existing.mkdir(parents=True)
    marker = existing / "marker.txt"
    marker.write_text("keep", encoding="utf-8")

    with pytest.raises(FileExistsError):
        run_uploaded_analysis(
            valid_upload_frame(), project_root, runs_root, run_id="upload_existing"
        )
    assert marker.read_text(encoding="utf-8") == "keep"
