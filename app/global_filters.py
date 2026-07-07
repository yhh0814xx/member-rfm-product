"""Apply one display-only filter pipeline to every dashboard view."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from .dashboard_data import (
    TRANSACTION_TABLE_SPECS,
    RunBundle,
    TransactionBundle,
    filter_customers,
    filter_transactions,
    summarize_filtered_countries,
    summarize_filtered_monthly,
    summarize_filtered_products,
)


EMPTY_FILTER_MESSAGE = "当前筛选条件下没有匹配数据，请调整筛选条件。"

SEGMENT_SUMMARY_COLUMNS = (
    "Segment",
    "CustomerCount",
    "MonetaryTotal",
    "AverageMonetary",
    "CustomerShare",
    "MonetaryShare",
)

COHORT_COLUMNS = (
    "CohortMonth",
    "Period",
    "Customers",
    "CohortSize",
    "RetentionRate",
)


@dataclass(frozen=True)
class GlobalFilterState:
    """Serializable values selected in the global display-filter sidebar."""

    date_range: tuple[Any, Any] | None = None
    countries: tuple[str, ...] = ()
    products: tuple[str, ...] = ()
    transaction_query: str = ""
    segments: tuple[str, ...] = ()
    customer_query: str = ""


@dataclass(frozen=True)
class GlobalFilterResult:
    """All display datasets derived from one filter state and immutable run."""

    filtered_transactions: pd.DataFrame
    eligible_customer_ids: frozenset[str]
    filtered_rfm_customers: pd.DataFrame
    filtered_segment_summary: pd.DataFrame
    filtered_monthly_summary: pd.DataFrame
    filtered_country_summary: pd.DataFrame
    filtered_product_summary: pd.DataFrame
    filtered_cohort: pd.DataFrame
    active_filter_summary: tuple[str, ...]
    transaction_available: bool


def normalize_customer_id(value: Any) -> str:
    """Normalize string, integer and integral-float customer identifiers."""
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        integer = text[:-2]
        if integer and integer.lstrip("-").isdigit():
            return integer
    return text


def normalize_customer_ids(values: pd.Series) -> pd.Series:
    """Return normalized identifiers with the original index preserved."""
    return values.map(normalize_customer_id).astype("string")


def build_filtered_segment_summary(customers: pd.DataFrame) -> pd.DataFrame:
    """Reaggregate display metrics without recalculating any RFM values."""
    if customers.empty:
        return pd.DataFrame(columns=SEGMENT_SUMMARY_COLUMNS)
    summary = (
        customers.groupby("Segment", as_index=False)
        .agg(
            CustomerCount=("CustomerID", "size"),
            MonetaryTotal=("Monetary", "sum"),
            AverageMonetary=("Monetary", "mean"),
        )
    )
    customer_total = int(summary["CustomerCount"].sum())
    monetary_total = float(summary["MonetaryTotal"].sum())
    summary["CustomerShare"] = summary["CustomerCount"] / customer_total
    summary["MonetaryShare"] = (
        summary["MonetaryTotal"] / monetary_total if monetary_total else 0.0
    )
    return summary.sort_values("MonetaryTotal", ascending=False).reset_index(drop=True)


def build_filtered_cohort(transactions: pd.DataFrame) -> pd.DataFrame:
    """Rebuild display-only cohort retention from the filtered transactions."""
    if transactions.empty:
        return pd.DataFrame(columns=COHORT_COLUMNS)
    prepared = transactions.dropna(subset=["CustomerID", "InvoiceDate"]).copy()
    if prepared.empty:
        return pd.DataFrame(columns=COHORT_COLUMNS)
    prepared["CustomerID"] = normalize_customer_ids(prepared["CustomerID"])
    prepared = prepared[prepared["CustomerID"].ne("")]
    if prepared.empty:
        return pd.DataFrame(columns=COHORT_COLUMNS)
    prepared["PurchaseMonth"] = (
        pd.to_datetime(prepared["InvoiceDate"], errors="raise")
        .dt.to_period("M")
        .dt.to_timestamp()
    )
    prepared["CohortMonth"] = prepared.groupby("CustomerID")["PurchaseMonth"].transform(
        "min"
    )
    prepared["Period"] = (
        (prepared["PurchaseMonth"].dt.year - prepared["CohortMonth"].dt.year) * 12
        + prepared["PurchaseMonth"].dt.month
        - prepared["CohortMonth"].dt.month
    )
    retention = (
        prepared.groupby(["CohortMonth", "Period"], as_index=False)["CustomerID"]
        .nunique()
        .rename(columns={"CustomerID": "Customers"})
    )
    cohort_sizes = (
        retention.loc[retention["Period"].eq(0), ["CohortMonth", "Customers"]]
        .set_index("CohortMonth")["Customers"]
        .rename("CohortSize")
    )
    retention = retention.join(cohort_sizes, on="CohortMonth")
    retention["RetentionRate"] = retention["Customers"] / retention["CohortSize"]
    retention["CohortMonth"] = retention["CohortMonth"].dt.strftime("%Y-%m")
    return retention.loc[:, COHORT_COLUMNS].sort_values(
        ["CohortMonth", "Period"]
    ).reset_index(drop=True)


def _empty_transaction_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=TRANSACTION_TABLE_SPECS["transaction_clean.csv"])


def _active_filter_summary(
    state: GlobalFilterState,
    customer_count: int,
    transaction_count: int,
    transaction_available: bool,
) -> tuple[str, ...]:
    lines: list[str] = []
    if state.countries:
        lines.append(f"国家：{'、'.join(state.countries)}")
    if state.date_range and len(state.date_range) == 2:
        start = pd.Timestamp(state.date_range[0]).date().isoformat()
        end = pd.Timestamp(state.date_range[1]).date().isoformat()
        lines.append(f"日期：{start}至{end}")
    if state.products:
        lines.append(f"商品：{'、'.join(state.products)}")
    if state.transaction_query.strip():
        lines.append(f"交易查询：{state.transaction_query.strip()}")
    if state.segments:
        lines.append(f"分层：{'、'.join(state.segments)}")
    if state.customer_query.strip():
        lines.append(f"CustomerID：{state.customer_query.strip()}")
    if not lines:
        lines.append("筛选条件：全部数据")
    lines.append(f"筛选后客户：{customer_count:,}")
    lines.append(
        f"筛选后交易：{transaction_count:,}"
        if transaction_available
        else "筛选后交易：不可用"
    )
    return tuple(lines)


def apply_global_filters(
    bundle: RunBundle,
    filter_state: GlobalFilterState,
    transaction_bundle: TransactionBundle | None = None,
) -> GlobalFilterResult:
    """Apply transaction filters, then customer filters, with AND semantics.

    Exported RFM values, Segment and clustering labels are only row-filtered;
    this function never invokes the pipeline or recalculates model outputs.
    """
    transaction_available = transaction_bundle is not None
    if transaction_bundle is None:
        transaction_candidates = _empty_transaction_frame()
        eligible_customer_ids = frozenset(
            normalize_customer_ids(bundle.rfm_customers["CustomerID"]).dropna().tolist()
        )
        eligible_rfm = bundle.rfm_customers.copy()
    else:
        transaction_candidates = filter_transactions(
            transaction_bundle.transactions,
            filter_state.date_range,
            list(filter_state.countries),
            list(filter_state.products),
            filter_state.transaction_query,
        )
        normalized_transaction_ids = normalize_customer_ids(
            transaction_candidates["CustomerID"]
        )
        eligible_customer_ids = frozenset(
            normalized_transaction_ids[normalized_transaction_ids.ne("")].tolist()
        )
        rfm_ids = normalize_customer_ids(bundle.rfm_customers["CustomerID"])
        eligible_rfm = bundle.rfm_customers.loc[
            rfm_ids.isin(eligible_customer_ids)
        ].copy()

    filtered_rfm = filter_customers(
        eligible_rfm,
        list(filter_state.segments),
        filter_state.customer_query,
    )
    final_customer_ids = frozenset(
        normalize_customer_ids(filtered_rfm["CustomerID"])
        .loc[lambda values: values.ne("")]
        .tolist()
    )
    if transaction_available:
        normalized_candidate_ids = normalize_customer_ids(
            transaction_candidates["CustomerID"]
        )
        filtered_transactions = transaction_candidates.loc[
            normalized_candidate_ids.isin(final_customer_ids)
        ].copy()
    else:
        filtered_transactions = transaction_candidates

    filtered_segment_summary = build_filtered_segment_summary(filtered_rfm)
    filtered_monthly = summarize_filtered_monthly(filtered_transactions)
    filtered_countries = summarize_filtered_countries(filtered_transactions)
    filtered_products = summarize_filtered_products(filtered_transactions)
    filtered_cohort = build_filtered_cohort(filtered_transactions)
    summary = _active_filter_summary(
        filter_state,
        len(filtered_rfm),
        len(filtered_transactions),
        transaction_available,
    )
    return GlobalFilterResult(
        filtered_transactions=filtered_transactions,
        eligible_customer_ids=eligible_customer_ids,
        filtered_rfm_customers=filtered_rfm,
        filtered_segment_summary=filtered_segment_summary,
        filtered_monthly_summary=filtered_monthly,
        filtered_country_summary=filtered_countries,
        filtered_product_summary=filtered_products,
        filtered_cohort=filtered_cohort,
        active_filter_summary=summary,
        transaction_available=transaction_available,
    )
