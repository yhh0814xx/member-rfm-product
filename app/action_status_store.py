"""SQLite-backed merchant action status storage for the dashboard session."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from src.customer_action_engine import ACTION_STATUSES


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "merchant_actions.sqlite"


def _connect(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS merchant_action_status (
            run_id TEXT NOT NULL,
            customer_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT '待联系',
            merchant_note TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (run_id, customer_id)
        )
        """
    )
    return connection


def load_statuses(run_id: str, customer_ids: list[str]) -> pd.DataFrame:
    """Load persisted statuses for the current run and visible customer IDs."""
    if not customer_ids:
        return pd.DataFrame(columns=["CustomerID", "Status", "MerchantNote"])
    placeholders = ",".join("?" for _ in customer_ids)
    try:
        with _connect() as connection:
            frame = pd.read_sql_query(
                f"""
                SELECT customer_id AS CustomerID,
                       status AS Status,
                       merchant_note AS MerchantNote
                FROM merchant_action_status
                WHERE run_id = ? AND customer_id IN ({placeholders})
                """,
                connection,
                params=[run_id, *customer_ids],
            )
    except sqlite3.Error:
        return pd.DataFrame(columns=["CustomerID", "Status", "MerchantNote"])
    return frame


def save_status(run_id: str, customer_id: str, status: str, merchant_note: str) -> None:
    """Persist one customer's action status and note."""
    if status not in ACTION_STATUSES:
        raise ValueError(f"未知处理状态：{status}")
    try:
        with _connect() as connection:
            connection.execute(
                """
                INSERT INTO merchant_action_status(run_id, customer_id, status, merchant_note)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(run_id, customer_id) DO UPDATE SET
                    status = excluded.status,
                    merchant_note = excluded.merchant_note,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (run_id, customer_id, status, merchant_note),
            )
    except sqlite3.Error as exc:
        raise RuntimeError("无法写入处理状态数据库，当前状态仅能在页面中临时查看。") from exc
