"""Build merchant-facing customer action queues from filtered run outputs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from .recommendation_adapter import normalize_customer_id
from .segment_recommendations import SEGMENTS, SegmentStrategy


DEFAULT_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "customer_message_templates_zh.json"
)

ACTION_STATUSES = ("待联系", "已联系", "待跟进", "已完成", "暂不联系")

ACTION_QUEUE_COLUMNS = (
    "CustomerID",
    "ChineseName",
    "Segment",
    "OperationGroup",
    "PriorityLevel",
    "ActionPriorityLabel",
    "ActionPriorityScore",
    "Recency",
    "Frequency",
    "Monetary",
    "LastPurchaseDate",
    "LastPurchasedProducts",
    "TopPurchasedProduct",
    "OrderCount",
    "TotalQuantity",
    "ContactReason",
    "NextBestAction",
    "ShortMessage",
    "CareMessage",
    "AvoidAction",
    "Status",
    "MerchantNote",
)

PRIORITY_RULES = {
    "Can't Lose Them": ("立即处理", 100, "不能失去的高价值客户"),
    "At Risk": ("优先跟进", 82, "历史有价值但近期活跃下降"),
    "Champions": ("重点维护", 80, "高价值活跃客户"),
    "Loyal Customers": ("重点维护", 75, "稳定复购客户"),
    "Need Attention": ("优先跟进", 70, "活跃度开始下降"),
    "Potential Loyalists": ("成长培育", 60, "具备忠诚成长潜力"),
    "New Customers": ("新客承接", 55, "需要完成首购承接"),
    "Promising": ("成长观察", 45, "已有初步购买信号"),
    "Hibernating": ("低成本触达", 35, "适合低成本唤醒"),
    "Lost": ("低优先级触达", 20, "长期未购买客户"),
}

SEGMENT_SORT_RANK = {
    "Can't Lose Them": 10,
    "At Risk": 9,
    "Champions": 8,
    "Loyal Customers": 7,
    "Need Attention": 6,
    "Potential Loyalists": 5,
    "New Customers": 4,
    "Promising": 3,
    "Hibernating": 2,
    "Lost": 1,
}

BANNED_MESSAGE_TERMS = (
    "流失概率",
    "AI预测",
    "转化概率",
    "CLV",
    "折扣",
    "优惠券",
    "赠品",
    "库存",
    "赔偿",
)


class CustomerActionConfigError(ValueError):
    """Message templates are incomplete or unsafe."""


@dataclass(frozen=True)
class MessageTemplate:
    """Chinese customer-contact templates for one segment."""

    short_message: str
    care_message: str
    recommended_action: str
    avoid_action: str


def load_message_templates(
    template_path: str | Path = DEFAULT_TEMPLATE_PATH,
) -> dict[str, MessageTemplate]:
    """Load and validate per-segment contact templates."""
    path = Path(template_path)
    if not path.is_file():
        raise CustomerActionConfigError(f"缺少客户话术模板文件：{path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CustomerActionConfigError(f"无法读取客户话术模板：{exc}") from exc
    if not isinstance(payload, dict):
        raise CustomerActionConfigError("客户话术模板顶层必须是对象。")

    templates: dict[str, MessageTemplate] = {}
    for segment in SEGMENTS:
        item = payload.get(segment)
        if not isinstance(item, dict):
            raise CustomerActionConfigError(f"缺少{segment}的话术模板。")
        missing = [
            field
            for field in ("ShortMessage", "CareMessage", "RecommendedAction", "AvoidAction")
            if not isinstance(item.get(field), str) or not item[field].strip()
        ]
        if missing:
            raise CustomerActionConfigError(
                f"{segment}的话术模板缺少字段：{', '.join(missing)}"
            )
        combined = " ".join(item[field] for field in item)
        banned = [term for term in BANNED_MESSAGE_TERMS if term in combined]
        if banned:
            raise CustomerActionConfigError(
                f"{segment}的话术模板包含不允许用语：{', '.join(banned)}"
            )
        templates[segment] = MessageTemplate(
            short_message=item["ShortMessage"].strip(),
            care_message=item["CareMessage"].strip(),
            recommended_action=item["RecommendedAction"].strip(),
            avoid_action=item["AvoidAction"].strip(),
        )
    extra = sorted(set(payload) - set(SEGMENTS))
    if extra:
        raise CustomerActionConfigError(f"发现未知Segment话术模板：{', '.join(extra)}")
    return templates


def _empty_transaction_features() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "CustomerID",
            "LastPurchaseDate",
            "LastPurchasedProducts",
            "TopPurchasedProduct",
            "OrderCount",
            "TotalQuantity",
        ]
    )


def build_transaction_features(transactions: pd.DataFrame | None) -> pd.DataFrame:
    """Summarize filtered transactions into customer-level product context."""
    if transactions is None or transactions.empty or "CustomerID" not in transactions:
        return _empty_transaction_features()
    required = {"CustomerID", "InvoiceNo", "InvoiceDate", "Description", "Quantity"}
    if not required.issubset(transactions.columns):
        return _empty_transaction_features()

    frame = transactions.copy()
    frame["CustomerID"] = frame["CustomerID"].map(normalize_customer_id)
    frame = frame[frame["CustomerID"].ne("")]
    if frame.empty:
        return _empty_transaction_features()
    frame["InvoiceDate"] = pd.to_datetime(frame["InvoiceDate"], errors="coerce")
    frame["Description"] = frame["Description"].fillna("").astype(str)
    frame["Quantity"] = pd.to_numeric(frame["Quantity"], errors="coerce").fillna(0)

    rows: list[dict[str, Any]] = []
    for customer_id, group in frame.groupby("CustomerID", sort=False):
        dated = group.dropna(subset=["InvoiceDate"])
        if dated.empty:
            last_date = ""
            last_products = ""
        else:
            last_ts = dated["InvoiceDate"].max()
            last_date = last_ts.date().isoformat()
            latest = dated[dated["InvoiceDate"].eq(last_ts)]
            last_products = "、".join(
                latest["Description"].replace("", pd.NA).dropna().drop_duplicates().head(3)
            )
        product_quantity = (
            group[group["Description"].ne("")]
            .groupby("Description")["Quantity"]
            .sum()
            .sort_values(ascending=False)
        )
        rows.append(
            {
                "CustomerID": customer_id,
                "LastPurchaseDate": last_date,
                "LastPurchasedProducts": last_products,
                "TopPurchasedProduct": (
                    str(product_quantity.index[0]) if not product_quantity.empty else ""
                ),
                "OrderCount": int(group["InvoiceNo"].nunique()),
                "TotalQuantity": float(group["Quantity"].sum()),
            }
        )
    return pd.DataFrame(rows)


def _format_context(row: Mapping[str, Any]) -> dict[str, str]:
    return {
        "customer_id": str(row.get("CustomerID", "")),
        "last_product": str(row.get("LastPurchasedProducts") or "最近购买商品"),
        "top_product": str(row.get("TopPurchasedProduct") or "常购商品"),
        "last_date": str(row.get("LastPurchaseDate") or "最近一次购买"),
        "frequency": f"{float(row.get('Frequency', 0)):,.0f}",
        "order_count": f"{int(row.get('OrderCount', 0)):,}",
    }


def _render_template(template: str, row: Mapping[str, Any]) -> str:
    return template.format(**_format_context(row))


def _priority_label_and_score(segment: str, monetary: float, monetary_threshold: float) -> tuple[str, float]:
    label, base_score, _ = PRIORITY_RULES.get(segment, ("低优先级触达", 10, ""))
    if segment == "At Risk" and monetary >= monetary_threshold:
        label = "立即处理"
        base_score = 92
    return label, float(base_score)


def _contact_reason(row: Mapping[str, Any], segment_note: str) -> str:
    money = float(row.get("Monetary", 0))
    frequency = float(row.get("Frequency", 0))
    recency = float(row.get("Recency", 0))
    top_product = str(row.get("TopPurchasedProduct") or "暂无明确常购商品")
    return (
        f"该客户历史消费金额为{money:,.0f}，累计购买{frequency:,.0f}次，"
        f"但已经{recency:,.0f}天没有再次购买，属于{segment_note}，"
        f"常购商品为{top_product}，建议按当前优先级联系。"
    )


def build_customer_action_queue(
    rfm_customers: pd.DataFrame,
    transactions: pd.DataFrame | None,
    strategies: Mapping[str, SegmentStrategy],
    templates: Mapping[str, MessageTemplate],
    *,
    statuses: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Return a filtered customer action queue sorted by deterministic business rules."""
    if rfm_customers.empty:
        return pd.DataFrame(columns=ACTION_QUEUE_COLUMNS)
    required = {"CustomerID", "Recency", "Frequency", "Monetary", "Segment"}
    missing = required - set(rfm_customers.columns)
    if missing:
        raise ValueError(f"客户行动队列缺少字段：{', '.join(sorted(missing))}")

    customers = rfm_customers.copy()
    customers["CustomerID"] = customers["CustomerID"].map(normalize_customer_id)
    for column in ("Recency", "Frequency", "Monetary"):
        customers[column] = pd.to_numeric(customers[column], errors="coerce").fillna(0)
    features = build_transaction_features(transactions)
    queue = customers.merge(features, on="CustomerID", how="left")
    for column in (
        "LastPurchaseDate",
        "LastPurchasedProducts",
        "TopPurchasedProduct",
    ):
        queue[column] = queue[column].fillna("")
    for column in ("OrderCount", "TotalQuantity"):
        queue[column] = pd.to_numeric(queue[column], errors="coerce").fillna(0)

    monetary_threshold = (
        float(queue["Monetary"].quantile(0.75)) if not queue.empty else 0.0
    )
    rows: list[dict[str, Any]] = []
    for row in queue.to_dict("records"):
        segment = str(row["Segment"])
        strategy = strategies[segment]
        template = templates[segment]
        label, base_score = _priority_label_and_score(
            segment, float(row["Monetary"]), monetary_threshold
        )
        money_rank_bonus = min(float(row["Monetary"]) / monetary_threshold, 1.0) * 7 if monetary_threshold else 0
        recency_bonus = min(float(row["Recency"]) / 365, 1.0) * 2
        frequency_bonus = min(float(row["Frequency"]) / 20, 1.0)
        score = round(min(base_score + money_rank_bonus + recency_bonus + frequency_bonus, 100), 2)
        segment_note = PRIORITY_RULES.get(segment, ("", 0, strategy.customer_characteristics))[2]
        enriched = dict(row)
        enriched.update(
            {
                "ChineseName": strategy.chinese_name,
                "OperationGroup": strategy.operation_group,
                "PriorityLevel": strategy.priority_level,
                "ActionPriorityLabel": label,
                "ActionPriorityScore": score,
                "ContactReason": _contact_reason(row, segment_note),
                "NextBestAction": _render_template(template.recommended_action, row),
                "ShortMessage": _render_template(template.short_message, row),
                "CareMessage": _render_template(template.care_message, row),
                "AvoidAction": _render_template(template.avoid_action, row),
                "SegmentSortRank": SEGMENT_SORT_RANK.get(segment, 0),
            }
        )
        rows.append(enriched)

    result = pd.DataFrame(rows)
    if statuses is not None and not statuses.empty:
        result = result.merge(statuses, on="CustomerID", how="left")
    else:
        result["Status"] = "待联系"
        result["MerchantNote"] = ""
    result["Status"] = result["Status"].fillna("待联系")
    result["MerchantNote"] = result["MerchantNote"].fillna("")
    result = result.sort_values(
        ["SegmentSortRank", "Monetary", "Recency", "Frequency", "CustomerID"],
        ascending=[False, False, False, False, True],
        kind="mergesort",
    )
    return result.loc[:, ACTION_QUEUE_COLUMNS].reset_index(drop=True)
