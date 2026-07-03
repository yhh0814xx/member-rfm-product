"""Safe upload validation and isolated orchestration of the existing pipeline."""

from __future__ import annotations

import io
import json
import math
import os
import secrets
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .dashboard_data import load_run, load_transaction_tables
from src.result_exporter import generate_run_id, validate_run_id
from src.rfm_pipeline import RFMPipeline


REQUIRED_COLUMNS = (
    "InvoiceNo",
    "StockCode",
    "Description",
    "Quantity",
    "InvoiceDate",
    "UnitPrice",
    "CustomerID",
    "Country",
)
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_UPLOAD_ROWS = 1_000_000
MIN_PROCESSABLE_CUSTOMERS = 16
PREVIEW_ROWS = 50


@dataclass
class UploadValidation:
    """Validation outcome plus the cleaned input accepted by the pipeline."""

    filename: str
    file_size: int
    total_rows: int
    processable_rows: int
    processable_customers: int
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    preview: pd.DataFrame
    cleaned_data: pd.DataFrame
    cleaning_stats: dict[str, int]

    @property
    def can_analyze(self) -> bool:
        return not self.errors and not self.cleaned_data.empty


@dataclass(frozen=True)
class AnalysisResult:
    """A successfully published immutable run."""

    run_id: str
    run_dir: Path
    stdout: str


class AnalysisExecutionError(RuntimeError):
    """Pipeline execution failed and a Chinese report was persisted."""

    def __init__(self, message: str, report_path: Path):
        super().__init__(message)
        self.report_path = report_path


def _safe_upload_name(filename: str) -> str:
    name = str(filename or "")
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        raise ValueError("上传文件名不安全，请重新选择文件")
    return name


def _empty_validation(
    filename: str, file_size: int, errors: list[str]
) -> UploadValidation:
    return UploadValidation(
        filename=filename,
        file_size=file_size,
        total_rows=0,
        processable_rows=0,
        processable_customers=0,
        errors=tuple(errors),
        warnings=(),
        preview=pd.DataFrame(),
        cleaned_data=pd.DataFrame(),
        cleaning_stats={},
    )


def _read_upload(filename: str, content: bytes) -> pd.DataFrame:
    suffix = Path(filename).suffix.lower()
    stream = io.BytesIO(content)
    if suffix == ".csv":
        return pd.read_csv(stream, nrows=MAX_UPLOAD_ROWS + 1)
    if suffix == ".xlsx":
        return pd.read_excel(
            stream, engine="openpyxl", sheet_name=0, nrows=MAX_UPLOAD_ROWS + 1
        )
    raise ValueError("仅支持CSV或XLSX文件")


def validate_upload(filename: str, content: bytes) -> UploadValidation:
    """Read an upload, report quality issues, and reuse the existing cleaner."""
    file_size = len(content)
    errors: list[str] = []
    warnings: list[str] = []
    try:
        safe_name = _safe_upload_name(filename)
    except ValueError as exc:
        return _empty_validation(str(filename), file_size, [str(exc)])

    if file_size == 0:
        return _empty_validation(safe_name, file_size, ["上传文件为空"])
    if file_size > MAX_UPLOAD_BYTES:
        return _empty_validation(
            safe_name,
            file_size,
            [f"文件超过{MAX_UPLOAD_BYTES // (1024 * 1024)} MiB限制"],
        )
    if Path(safe_name).suffix.lower() not in {".csv", ".xlsx"}:
        return _empty_validation(safe_name, file_size, ["仅支持CSV或XLSX文件"])

    try:
        frame = _read_upload(safe_name, content)
    except Exception as exc:
        return _empty_validation(safe_name, file_size, [f"文件读取失败：{exc}"])

    total_rows = len(frame)
    preview = frame.head(PREVIEW_ROWS).copy()
    if total_rows == 0:
        errors.append("文件没有数据行")
    if total_rows > MAX_UPLOAD_ROWS:
        errors.append(f"数据行数超过{MAX_UPLOAD_ROWS:,}行限制")

    missing_columns = [column for column in REQUIRED_COLUMNS if column not in frame]
    if missing_columns:
        errors.append(f"缺少必需字段：{', '.join(missing_columns)}")
        return UploadValidation(
            safe_name,
            file_size,
            total_rows,
            0,
            0,
            tuple(errors),
            tuple(warnings),
            preview,
            pd.DataFrame(),
            {},
        )

    prepared = frame.copy()
    parsed_dates = pd.to_datetime(
        prepared["InvoiceDate"], errors="coerce", format="mixed"
    )
    invalid_dates = int(parsed_dates.isna().sum())
    if invalid_dates:
        errors.append(f"InvoiceDate存在{invalid_dates:,}条无效或缺失日期")
    elif parsed_dates.nunique() <= 1:
        errors.append(
            "所有交易日期完全相同，无法计算有效的RFM Recency五分位，请提供包含不同交易日期的数据"
        )
    prepared["InvoiceDate"] = parsed_dates

    for column in ("Quantity", "UnitPrice"):
        numeric = pd.to_numeric(prepared[column], errors="coerce")
        invalid_numeric = int((numeric.isna() | ~numeric.map(math.isfinite)).sum())
        if invalid_numeric:
            errors.append(f"{column}存在{invalid_numeric:,}条非数值或非有限值")
        prepared[column] = numeric

    missing_customer = prepared["CustomerID"].isna() | prepared[
        "CustomerID"
    ].astype("string").str.strip().eq("")
    missing_customer_count = int(missing_customer.sum())
    if missing_customer_count:
        warnings.append(
            f"CustomerID缺失{missing_customer_count:,}行，将由现有清洗规则删除"
        )
        prepared.loc[missing_customer, "CustomerID"] = pd.NA

    duplicate_count = int(prepared.duplicated().sum())
    if duplicate_count:
        warnings.append(f"发现{duplicate_count:,}条精确重复记录，将删除")

    if not prepared[["Quantity", "UnitPrice"]].isna().any().any():
        nonpositive = int(
            ((prepared["Quantity"] <= 0) | (prepared["UnitPrice"] <= 0)).sum()
        )
        if nonpositive:
            warnings.append(
                f"发现{nonpositive:,}条Quantity或UnitPrice非正记录，将删除"
            )

    cancelled = int(prepared["InvoiceNo"].astype(str).str.startswith("C").sum())
    if cancelled:
        warnings.append(f"发现{cancelled:,}条取消订单记录，将删除")

    for column in ("StockCode", "Description", "Country"):
        missing_values = int(prepared[column].isna().sum())
        if missing_values:
            warnings.append(f"{column}存在{missing_values:,}个缺失值")

    cleaned = pd.DataFrame()
    cleaning_stats: dict[str, int] = {}
    if not errors:
        cleaned, raw_stats = RFMPipeline().clean_data(prepared)
        cleaning_stats = {key: int(value) for key, value in raw_stats.items()}
        processable_customers = int(cleaned["CustomerID"].nunique())
        if cleaned.empty:
            errors.append("现有清洗规则处理后没有可分析数据")
        elif processable_customers < MIN_PROCESSABLE_CUSTOMERS:
            errors.append(
                f"可处理客户仅{processable_customers:,}个，现有聚类流程至少需要"
                f"{MIN_PROCESSABLE_CUSTOMERS}个客户"
            )
    processable_rows = len(cleaned)
    processable_customers = (
        int(cleaned["CustomerID"].nunique()) if not cleaned.empty else 0
    )
    return UploadValidation(
        filename=safe_name,
        file_size=file_size,
        total_rows=total_rows,
        processable_rows=processable_rows,
        processable_customers=processable_customers,
        errors=tuple(errors),
        warnings=tuple(warnings),
        preview=preview,
        cleaned_data=cleaned,
        cleaning_stats=cleaning_stats,
    )


def generate_upload_run_id(runs_root: Path) -> str:
    """Generate a safe collision-resistant id that cannot overwrite a run."""
    runs_root = Path(runs_root).resolve()
    for _ in range(10):
        run_id = validate_run_id(f"upload_{generate_run_id()}")
        if not (runs_root / run_id).exists():
            return run_id
    raise RuntimeError("无法生成唯一run_id，请稍后重试")


def _write_error_report(
    errors_root: Path,
    run_id: str,
    stage: str,
    message: str,
    stdout: str = "",
    stderr: str = "",
) -> Path:
    errors_root.mkdir(parents=True, exist_ok=True)
    path = errors_root / f"{run_id}_error.json"
    payload = {
        "状态": "失败",
        "run_id": run_id,
        "失败阶段": stage,
        "时间_UTC": datetime.now(timezone.utc).isoformat(),
        "错误": message,
        "标准输出末尾": stdout[-4000:],
        "标准错误末尾": stderr[-4000:],
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path


def run_uploaded_analysis(
    cleaned_data: pd.DataFrame,
    project_root: Path,
    runs_root: Path,
    run_id: str | None = None,
    python_executable: Path | None = None,
    timeout_seconds: int = 3600,
) -> AnalysisResult:
    """Run the existing CLI in staging and atomically publish a verified run."""
    project_root = Path(project_root).resolve()
    runs_root = Path(runs_root).resolve()
    selected_id = validate_run_id(run_id) if run_id else generate_upload_run_id(runs_root)
    final_run = runs_root / selected_id
    if final_run.exists():
        raise FileExistsError(f"run_id已存在，拒绝覆盖：{selected_id}")

    outputs_root = runs_root.parent
    staging_base = outputs_root / ".staging"
    errors_root = outputs_root / "errors"
    locks_root = outputs_root / ".locks"
    staging_base.mkdir(parents=True, exist_ok=True)
    locks_root.mkdir(parents=True, exist_ok=True)
    job_root = staging_base / f"{selected_id}_{secrets.token_hex(4)}"
    job_root.mkdir(exist_ok=False)
    lock_path = locks_root / f"{selected_id}.lock"
    stage = "准备分析"
    stdout = ""
    stderr = ""

    try:
        with lock_path.open("x", encoding="utf-8") as lock:
            lock.write(str(os.getpid()))
        input_path = job_root / "validated_input.csv"
        cleaned_data.to_csv(input_path, index=False, encoding="utf-8")
        executable = Path(python_executable) if python_executable else Path(os.sys.executable)
        command = [
            str(executable),
            str(project_root / "run_pipeline.py"),
            "--input",
            str(input_path),
            "--output-root",
            str(job_root),
            "--run-id",
            selected_id,
        ]
        stage = "运行现有pipeline"
        completed = subprocess.run(
            command,
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            shell=False,
        )
        stdout, stderr = completed.stdout, completed.stderr
        if completed.returncode != 0:
            raise RuntimeError(
                f"现有pipeline返回退出码{completed.returncode}："
                f"{(stderr or stdout)[-1000:]}"
            )

        staged_run = job_root / selected_id
        stage = "验证分析结果"
        load_run(staged_run)
        load_transaction_tables(staged_run)
        if final_run.exists():
            raise FileExistsError(f"run_id已存在，拒绝覆盖：{selected_id}")
        runs_root.mkdir(parents=True, exist_ok=True)
        stage = "发布分析结果"
        staged_run.replace(final_run)
        return AnalysisResult(selected_id, final_run, stdout)
    except Exception as exc:
        report_path = _write_error_report(
            errors_root, selected_id, stage, str(exc), stdout, stderr
        )
        raise AnalysisExecutionError(
            f"分析失败：{exc}；错误报告：{report_path}", report_path
        ) from exc
    finally:
        if job_root.exists():
            shutil.rmtree(job_root, ignore_errors=True)
        lock_path.unlink(missing_ok=True)
