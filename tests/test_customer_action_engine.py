"""Tests for deterministic customer action queue generation."""

from __future__ import annotations

from io import BytesIO

import pandas as pd

from src.customer_action_engine import (
    BANNED_MESSAGE_TERMS,
    build_customer_action_queue,
    build_transaction_features,
    load_message_templates,
)
from src.segment_recommendations import SEGMENTS, load_segment_strategies


def make_rfm() -> pd.DataFrame:
    rows = []
    for index, segment in enumerate(SEGMENTS):
        rows.append(
            {
                "CustomerID": f"{1000 + index}.0",
                "Recency": 20 + index * 10,
                "Frequency": 10 - index if index < 9 else 1,
                "Monetary": (index + 1) * 100.0,
                "Segment": segment,
            }
        )
    extra = pd.DataFrame(
        [
            {
                "CustomerID": "2001.0",
                "Recency": 180,
                "Frequency": 7,
                "Monetary": 9000.0,
                "Segment": "At Risk",
            },
            {
                "CustomerID": "2002.0",
                "Recency": 210,
                "Frequency": 9,
                "Monetary": 8500.0,
                "Segment": "At Risk",
            },
        ]
    )
    return pd.concat([pd.DataFrame(rows), extra], ignore_index=True)


def make_transactions() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"InvoiceNo": "I1", "CustomerID": "2001.0", "InvoiceDate": "2025-01-01", "Description": "Alpha", "Quantity": 2},
            {"InvoiceNo": "I2", "CustomerID": "2001.0", "InvoiceDate": "2025-02-01", "Description": "Beta", "Quantity": 5},
            {"InvoiceNo": "I3", "CustomerID": "2001.0", "InvoiceDate": "2025-02-01", "Description": "Alpha", "Quantity": 6},
            {"InvoiceNo": "I4", "CustomerID": "1003.0", "InvoiceDate": "2025-03-01", "Description": "New Product", "Quantity": 1},
        ]
    )


def build_queue(rfm: pd.DataFrame | None = None, transactions: pd.DataFrame | None = None) -> pd.DataFrame:
    return build_customer_action_queue(
        make_rfm() if rfm is None else rfm,
        make_transactions() if transactions is None else transactions,
        load_segment_strategies(),
        load_message_templates(),
    )


def test_operation_priority_order_is_correct():
    queue = build_queue()
    assert queue.iloc[0]["Segment"] == "Can't Lose Them"
    assert queue.iloc[0]["ActionPriorityLabel"] == "立即处理"
    assert queue.iloc[1]["Segment"] == "At Risk"


def test_same_segment_sorts_by_monetary_then_recency_then_frequency():
    rfm = pd.DataFrame(
        [
            {"CustomerID": "A", "Recency": 10, "Frequency": 1, "Monetary": 100, "Segment": "Champions"},
            {"CustomerID": "B", "Recency": 50, "Frequency": 1, "Monetary": 200, "Segment": "Champions"},
            {"CustomerID": "C", "Recency": 60, "Frequency": 2, "Monetary": 200, "Segment": "Champions"},
        ]
    )
    queue = build_queue(rfm=rfm, transactions=pd.DataFrame())
    assert queue["CustomerID"].tolist() == ["C", "B", "A"]


def test_each_customer_has_reason_and_next_action():
    queue = build_queue()
    assert queue["ContactReason"].str.contains("历史消费金额").all()
    assert queue["NextBestAction"].str.len().gt(0).all()


def test_all_ten_segments_have_safe_message_templates():
    templates = load_message_templates()
    assert set(templates) == set(SEGMENTS)
    combined = " ".join(
        " ".join([t.short_message, t.care_message, t.recommended_action, t.avoid_action])
        for t in templates.values()
    )
    assert not any(term in combined for term in BANNED_MESSAGE_TERMS)
    assert "客户姓名" not in combined


def test_customer_detail_uses_correct_transaction_records_and_products():
    features = build_transaction_features(make_transactions()).set_index("CustomerID")
    assert features.loc["2001", "LastPurchaseDate"] == "2025-02-01"
    assert "Beta" in features.loc["2001", "LastPurchasedProducts"]
    assert features.loc["2001", "TopPurchasedProduct"] == "Alpha"
    assert features.loc["2001", "OrderCount"] == 3
    assert features.loc["2001", "TotalQuantity"] == 13


def test_filtered_queue_and_download_match():
    queue = build_queue().query("Segment == 'At Risk'").reset_index(drop=True)
    downloaded = pd.read_csv(BytesIO(queue.to_csv(index=False).encode("utf-8-sig")))
    assert len(downloaded) == len(queue)
    assert downloaded["CustomerID"].astype(str).tolist() == queue["CustomerID"].astype(str).tolist()
