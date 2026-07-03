#!/usr/bin/env python
"""CLI entrypoint for the full RFM customer segmentation pipeline.

Loads cleaned transaction data, computes RFM scores and segments,
runs K-Means and GMM clustering with multiple preprocessing methods,
and generates seven visualizations including an algorithm comparison.

Usage
-----
    python run_pipeline.py --output-root outputs/runs
    python run_pipeline.py --output-root outputs/runs --run-id test_run
"""

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401  (side-effect import)

from src.rfm_pipeline import RFMPipeline
from src.result_exporter import (
    build_segment_summary,
    create_run_directory,
    export_tables,
    export_transaction_tables,
    relative_manifest,
    runtime_versions,
    sha256_file,
    write_metadata,
)


# ======================================================================
# Argument parsing
# ======================================================================

def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Run the full RFM analysis pipeline and regenerate all visualizations."
    )
    parser.add_argument(
        "--input",
        default="data/online_retail_clean.csv",
        help="Path to the cleaned transaction CSV (default: data/online_retail_clean.csv)",
    )
    parser.add_argument(
        "--output-root",
        default="outputs/runs",
        help="Root directory for isolated runs (default: outputs/runs)",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Optional unique run identifier; existing run directories are never overwritten",
    )
    parser.add_argument(
        "--k",
        type=int,
        default=4,
        help="Number of K-Means clusters (default: 4)",
    )
    return parser.parse_args(argv)


# ======================================================================
# Visualization helpers
# ======================================================================

def save_figure(fig, output_dir, filename):
    """Save a matplotlib figure and close it."""
    path = os.path.join(output_dir, filename)
    fig.savefig(path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {path}")


# ------------------------------------------------------------------
# 1. Segment Overview Dashboard
# ------------------------------------------------------------------

def plot_segment_overview(rfm, output_dir):
    """4-panel dashboard: segment distribution, revenue by segment,
    avg revenue per customer, priority matrix."""
    plt.style.use("seaborn-v0_8-darkgrid")
    sns.set_palette("husl")

    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    fig.suptitle(
        "RFM Customer Segmentation - Overview Dashboard",
        fontsize=20, fontweight="bold", y=0.995,
    )

    # --- Panel 1: Segment Distribution (customer count) ---
    segment_counts = rfm["Segment"].value_counts().sort_values(ascending=True)
    colors = [
        "#FF6B6B" if x in ["Lost", "Hibernating", "At Risk", "Can't Lose Them"]
        else "#4ECDC4" if x in ["Champions", "Loyal Customers"]
        else "#95E1D3"
        for x in segment_counts.index
    ]

    axes[0, 0].barh(segment_counts.index, segment_counts.values, color=colors)
    axes[0, 0].set_xlabel("Number of Customers", fontsize=12, fontweight="bold")
    axes[0, 0].set_title("Customer Distribution by Segment", fontsize=14, fontweight="bold")
    for i, v in enumerate(segment_counts.values):
        axes[0, 0].text(v + 20, i, f"{v} ({v / len(rfm) * 100:.1f}%)", va="center", fontweight="bold")

    # --- Panel 2: Revenue by Segment ---
    segment_revenue = rfm.groupby("Segment")["Monetary"].sum().sort_values(ascending=True)
    colors_rev = [
        "#FF6B6B" if x in ["Lost", "Hibernating", "At Risk", "Can't Lose Them"]
        else "#4ECDC4" if x in ["Champions", "Loyal Customers"]
        else "#95E1D3"
        for x in segment_revenue.index
    ]

    axes[0, 1].barh(segment_revenue.index, segment_revenue.values, color=colors_rev)
    axes[0, 1].set_xlabel("Total Revenue (GBP)", fontsize=12, fontweight="bold")
    axes[0, 1].set_title("Revenue Contribution by Segment", fontsize=14, fontweight="bold")
    for i, v in enumerate(segment_revenue.values):
        axes[0, 1].text(v + 50000, i, f"GBP {v / 1000:.0f}k", va="center", fontweight="bold")

    # --- Panel 3: Average Revenue per Customer ---
    avg_revenue = rfm.groupby("Segment")["Monetary"].mean().sort_values(ascending=True)
    axes[1, 0].barh(avg_revenue.index, avg_revenue.values, color="#FFA07A")
    axes[1, 0].set_xlabel("Average Customer Value (GBP)", fontsize=12, fontweight="bold")
    axes[1, 0].set_title("Average Revenue per Customer by Segment", fontsize=14, fontweight="bold")
    for i, v in enumerate(avg_revenue.values):
        axes[1, 0].text(v + 100, i, f"GBP {v:.0f}", va="center", fontweight="bold")

    # --- Panel 4: Segment Priority Matrix ---
    segment_summary = pd.DataFrame({
        "Customer_Pct": (rfm["Segment"].value_counts() / len(rfm) * 100),
        "Revenue_Pct": (rfm.groupby("Segment")["Monetary"].sum() / rfm["Monetary"].sum() * 100),
    })

    colors_scatter = {
        "Champions": "#4ECDC4", "Loyal Customers": "#95E1D3",
        "At Risk": "#FF6B6B", "Lost": "#C44569",
        "Hibernating": "#FFB6B9", "New Customers": "#A8E6CF",
        "Promising": "#FDFD96", "Can't Lose Them": "#FF6B6B",
        "Potential Loyalists": "#B4E7CE", "Need Attention": "#FFAAA5",
    }

    for segment in segment_summary.index:
        axes[1, 1].scatter(
            segment_summary.loc[segment, "Customer_Pct"],
            segment_summary.loc[segment, "Revenue_Pct"],
            s=500, alpha=0.7,
            color=colors_scatter.get(segment, "gray"),
            edgecolors="black", linewidth=2,
        )
        axes[1, 1].annotate(
            segment,
            (segment_summary.loc[segment, "Customer_Pct"],
             segment_summary.loc[segment, "Revenue_Pct"]),
            fontsize=9, ha="center", va="center", fontweight="bold",
        )

    axes[1, 1].axhline(y=10, color="red", linestyle="--", alpha=0.5, label="10% Revenue")
    axes[1, 1].axvline(x=10, color="blue", linestyle="--", alpha=0.5, label="10% Customers")
    axes[1, 1].set_xlabel("% of Total Customers", fontsize=12, fontweight="bold")
    axes[1, 1].set_ylabel("% of Total Revenue", fontsize=12, fontweight="bold")
    axes[1, 1].set_title(
        "Segment Priority Matrix\n(Higher Right = High Value)", fontsize=14, fontweight="bold"
    )
    axes[1, 1].legend()
    axes[1, 1].grid(True, alpha=0.3)

    fig.tight_layout()
    save_figure(fig, output_dir, "1_rfm_segment_overview.png")


# ------------------------------------------------------------------
# 2. Executive Summary Dashboard
# ------------------------------------------------------------------

def plot_executive_summary(rfm, output_dir):
    """4-panel: revenue risk pie, lifecycle funnel, action priority map,
    revenue projection."""
    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    fig.suptitle("RFM Analysis - Executive Summary", fontsize=22, fontweight="bold", y=0.995)

    # --- Panel 1: Revenue Risk Analysis ---
    risk_segments = {
        "Safe Revenue": rfm[rfm["Segment"].isin(["Champions", "Loyal Customers"])]["Monetary"].sum(),
        "At Risk Revenue": rfm[rfm["Segment"].isin(["At Risk", "Can't Lose Them", "Need Attention"])]["Monetary"].sum(),
        "Lost Revenue": rfm[rfm["Segment"].isin(["Lost", "Hibernating"])]["Monetary"].sum(),
        "Growth Potential": rfm[rfm["Segment"].isin(["New Customers", "Promising", "Potential Loyalists"])]["Monetary"].sum(),
    }

    colors_risk = ["#2ECC71", "#E74C3C", "#95A5A6", "#3498DB"]
    explode = (0.05, 0.15, 0.05, 0.05)

    wedges, texts, autotexts = axes[0, 0].pie(
        risk_segments.values(),
        labels=risk_segments.keys(),
        autopct="%1.1f%%",
        colors=colors_risk,
        explode=explode,
        startangle=90,
        textprops={"fontsize": 11, "fontweight": "bold"},
    )
    axes[0, 0].set_title("Revenue Risk Profile\n(Where is your money?)", fontsize=14, fontweight="bold")

    legend_labels = [f"{k}: GBP {v / 1000:.0f}k" for k, v in risk_segments.items()]
    axes[0, 0].legend(legend_labels, loc="upper left", bbox_to_anchor=(0.85, 1), fontsize=10)

    # --- Panel 2: Customer Lifecycle Funnel ---
    lifecycle_data = {
        "New Customers": len(rfm[rfm["Segment"] == "New Customers"]),
        "Potential Loyalists": len(rfm[rfm["Segment"] == "Potential Loyalists"]),
        "Loyal Customers": len(rfm[rfm["Segment"] == "Loyal Customers"]),
        "Champions": len(rfm[rfm["Segment"] == "Champions"]),
    }

    y_pos = np.arange(len(lifecycle_data))
    bars = axes[0, 1].barh(
        y_pos, list(lifecycle_data.values()),
        color=["#AED6F1", "#85C1E2", "#5DADE2", "#2E86C1"],
    )
    axes[0, 1].set_yticks(y_pos)
    axes[0, 1].set_yticklabels(lifecycle_data.keys(), fontsize=11, fontweight="bold")
    axes[0, 1].set_xlabel("Number of Customers", fontsize=12, fontweight="bold")
    axes[0, 1].set_title(
        "Customer Lifecycle Progression\n(Are customers moving up?)", fontsize=14, fontweight="bold"
    )
    axes[0, 1].invert_yaxis()

    for i, (bar, count) in enumerate(zip(bars, lifecycle_data.values())):
        axes[0, 1].text(count + 20, i, f"{count}", va="center", fontweight="bold", fontsize=11)

    # --- Panel 3: Action Priorities ---
    priority_segments = ["Champions", "At Risk", "Can't Lose Them", "Loyal Customers", "New Customers"]
    priority_data = []
    for seg in priority_segments:
        seg_data = rfm[rfm["Segment"] == seg]
        priority_data.append({
            "Segment": seg,
            "Count": len(seg_data),
            "Revenue": seg_data["Monetary"].sum(),
            "Avg_Value": seg_data["Monetary"].mean(),
        })

    priority_df = pd.DataFrame(priority_data)

    x_positions = [5, 1, 1, 4, 3]
    y_values = priority_df["Revenue"].values / 1000

    colors_priority = ["#2ECC71", "#E74C3C", "#E67E22", "#3498DB", "#9B59B6"]
    sizes = priority_df["Count"].values * 3

    for i, (x, y, size, color, seg) in enumerate(
        zip(x_positions, y_values, sizes, colors_priority, priority_segments)
    ):
        axes[1, 0].scatter(x, y, s=size, alpha=0.6, color=color, edgecolors="black", linewidth=2)
        axes[1, 0].annotate(
            f"{seg}\n{priority_df.loc[i, 'Count']} customers\nGBP {y:.0f}k",
            (x, y), ha="center", va="center", fontsize=9, fontweight="bold",
        )

    axes[1, 0].set_xlim(0, 6)
    axes[1, 0].set_xlabel("Action Type", fontsize=12, fontweight="bold")
    axes[1, 0].set_ylabel("Revenue (GBP k)", fontsize=12, fontweight="bold")
    axes[1, 0].set_xticks([1, 2, 3, 4, 5])
    axes[1, 0].set_xticklabels(
        ["RESCUE", "PREVENT", "GROW", "NURTURE", "RETAIN"], fontsize=10, fontweight="bold"
    )
    axes[1, 0].set_title(
        "Action Priority Map\n(Bubble size = number of customers)", fontsize=14, fontweight="bold"
    )
    axes[1, 0].grid(True, alpha=0.3)

    # --- Panel 4: Revenue Projection ---
    months = ["Now", "+1M", "+2M", "+3M", "+6M", "+12M"]
    champion_revenue = rfm[rfm["Segment"] == "Champions"]["Monetary"].sum()
    loyal_revenue = rfm[rfm["Segment"] == "Loyal Customers"]["Monetary"].sum()
    atrisk_revenue = rfm[rfm["Segment"].isin(["At Risk", "Can't Lose Them"])]["Monetary"].sum()

    best_case = [
        champion_revenue + loyal_revenue + atrisk_revenue,
        champion_revenue * 1.05 + loyal_revenue * 1.02 + atrisk_revenue * 0.9,
        champion_revenue * 1.1 + loyal_revenue * 1.05 + atrisk_revenue * 0.7,
        champion_revenue * 1.15 + loyal_revenue * 1.08 + atrisk_revenue * 0.5,
        champion_revenue * 1.25 + loyal_revenue * 1.15 + atrisk_revenue * 0.2,
        champion_revenue * 1.4 + loyal_revenue * 1.3 + atrisk_revenue * 0.05,
    ]

    worst_case = [
        champion_revenue + loyal_revenue + atrisk_revenue,
        champion_revenue * 0.95 + loyal_revenue * 0.9 + atrisk_revenue * 0.5,
        champion_revenue * 0.9 + loyal_revenue * 0.8 + atrisk_revenue * 0.2,
        champion_revenue * 0.85 + loyal_revenue * 0.7 + atrisk_revenue * 0.05,
        champion_revenue * 0.75 + loyal_revenue * 0.6 + atrisk_revenue * 0,
        champion_revenue * 0.6 + loyal_revenue * 0.5 + atrisk_revenue * 0,
    ]

    axes[1, 1].plot(
        months, [x / 1e6 for x in best_case], marker="o", linewidth=3,
        color="#2ECC71", label="Best Case (retain + grow)", markersize=10,
    )
    axes[1, 1].plot(
        months, [x / 1e6 for x in worst_case], marker="o", linewidth=3,
        color="#E74C3C", label="Worst Case (lose customers)", markersize=10,
    )
    axes[1, 1].fill_between(
        range(len(months)),
        [x / 1e6 for x in worst_case],
        [x / 1e6 for x in best_case],
        alpha=0.2, color="gray",
    )

    axes[1, 1].set_xlabel("Time Horizon", fontsize=12, fontweight="bold")
    axes[1, 1].set_ylabel("Revenue (Million GBP)", fontsize=12, fontweight="bold")
    axes[1, 1].set_title("Revenue Projection Scenarios", fontsize=14, fontweight="bold")
    axes[1, 1].legend(fontsize=10)
    axes[1, 1].grid(True, alpha=0.3)

    fig.tight_layout()
    save_figure(fig, output_dir, "2_rfm_executive_summary.png")


# ------------------------------------------------------------------
# 3. 3D RFM Scatter Plot
# ------------------------------------------------------------------

def plot_3d_scatter(rfm, output_dir):
    """4-panel: 3D scatter by segment, recency vs frequency,
    frequency vs monetary, recency vs monetary."""
    rfm_sample = rfm.sample(n=min(1000, len(rfm)), random_state=42)

    fig = plt.figure(figsize=(16, 12))

    segment_colors = {
        "Champions": "#4ECDC4",
        "Loyal Customers": "#95E1D3",
        "At Risk": "#FF6B6B",
        "Lost": "#C44569",
        "Hibernating": "#FFB6B9",
        "New Customers": "#A8E6CF",
        "Promising": "#FDFD96",
        "Can't Lose Them": "#FF0000",
        "Potential Loyalists": "#B4E7CE",
        "Need Attention": "#FFAAA5",
    }

    # --- Panel 1: 3D Scatter with segments ---
    ax1 = fig.add_subplot(221, projection="3d")
    for segment in rfm_sample["Segment"].unique():
        segment_data = rfm_sample[rfm_sample["Segment"] == segment]
        ax1.scatter(
            segment_data["Recency"],
            segment_data["Frequency"],
            segment_data["Monetary"],
            c=segment_colors.get(segment, "gray"),
            label=segment, s=50, alpha=0.6,
            edgecolors="black", linewidth=0.5,
        )
    ax1.set_xlabel("Recency (Days)", fontsize=12, fontweight="bold")
    ax1.set_ylabel("Frequency (Purchases)", fontsize=12, fontweight="bold")
    ax1.set_zlabel("Monetary (GBP)", fontsize=12, fontweight="bold")
    ax1.set_title("3D RFM Distribution by Segment", fontsize=14, fontweight="bold")
    ax1.legend(loc="upper left", fontsize=8)

    # --- Panel 2: Recency vs Frequency (colored by Monetary) ---
    ax2 = fig.add_subplot(222)
    scatter = ax2.scatter(
        rfm_sample["Recency"], rfm_sample["Frequency"],
        c=rfm_sample["Monetary"], cmap="YlOrRd",
        s=100, alpha=0.6, edgecolors="black", linewidth=0.5,
    )
    ax2.set_xlabel("Recency (Days)", fontsize=12, fontweight="bold")
    ax2.set_ylabel("Frequency (Purchases)", fontsize=12, fontweight="bold")
    ax2.set_title("Recency vs Frequency\n(Color = Monetary Value)", fontsize=14, fontweight="bold")
    plt.colorbar(scatter, ax=ax2, label="Monetary (GBP)")
    ax2.grid(True, alpha=0.3)

    # --- Panel 3: Frequency vs Monetary (colored by Recency) ---
    ax3 = fig.add_subplot(223)
    scatter2 = ax3.scatter(
        rfm_sample["Frequency"], rfm_sample["Monetary"],
        c=rfm_sample["Recency"], cmap="RdYlGn_r",
        s=100, alpha=0.6, edgecolors="black", linewidth=0.5,
    )
    ax3.set_xlabel("Frequency (Purchases)", fontsize=12, fontweight="bold")
    ax3.set_ylabel("Monetary (GBP)", fontsize=12, fontweight="bold")
    ax3.set_title("Frequency vs Monetary\n(Color = Recency)", fontsize=14, fontweight="bold")
    plt.colorbar(scatter2, ax=ax3, label="Recency (Days)")
    ax3.grid(True, alpha=0.3)

    # --- Panel 4: Recency vs Monetary (colored by Frequency) ---
    ax4 = fig.add_subplot(224)
    scatter3 = ax4.scatter(
        rfm_sample["Recency"], rfm_sample["Monetary"],
        c=rfm_sample["Frequency"], cmap="viridis",
        s=100, alpha=0.6, edgecolors="black", linewidth=0.5,
    )
    ax4.set_xlabel("Recency (Days)", fontsize=12, fontweight="bold")
    ax4.set_ylabel("Monetary (GBP)", fontsize=12, fontweight="bold")
    ax4.set_title("Recency vs Monetary\n(Color = Frequency)", fontsize=14, fontweight="bold")
    plt.colorbar(scatter3, ax=ax4, label="Frequency")
    ax4.grid(True, alpha=0.3)

    fig.tight_layout()
    save_figure(fig, output_dir, "3_rfm_3d_scatter.png")


# ------------------------------------------------------------------
# 4. Action Cards
# ------------------------------------------------------------------

def plot_action_cards(rfm, output_dir):
    """9 segment action cards -- marketing playbook."""
    fig = plt.figure(figsize=(18, 14))
    gs = fig.add_gridspec(3, 3, hspace=0.45, wspace=0.25)
    fig.suptitle(
        "RFM Segment Action Cards - Marketing Playbook",
        fontsize=22, fontweight="bold", y=0.98,
    )

    segments_to_show = [
        "Champions", "Loyal Customers", "At Risk",
        "Can't Lose Them", "New Customers", "Promising",
        "Hibernating", "Lost", "Need Attention",
    ]

    segment_actions = {
        "Champions": {
            "color": "#2ECC71",
            "label": "Champions",
            "action": "RETAIN & REWARD",
            "tactics": ["VIP Program", "Early Access", "Referral Bonus", "Exclusive Events"],
            "priority": "HIGH",
        },
        "Loyal Customers": {
            "color": "#3498DB",
            "label": "Loyal Customers",
            "action": "UPSELL & ENGAGE",
            "tactics": ["Cross-sell Products", "Loyalty Points", "Premium Tier", "Personalization"],
            "priority": "HIGH",
        },
        "At Risk": {
            "color": "#E74C3C",
            "label": "At Risk",
            "action": "WIN-BACK NOW",
            "tactics": ["Personal Email", "20% Discount Offer", "Feedback Survey", "Re-engagement"],
            "priority": "URGENT",
        },
        "Can't Lose Them": {
            "color": "#C0392B",
            "label": "Can't Lose Them",
            "action": "EMERGENCY RESCUE",
            "tactics": ["Phone Call", "Exclusive VIP Offer", "Account Manager", "Priority Support"],
            "priority": "CRITICAL",
        },
        "New Customers": {
            "color": "#9B59B6",
            "label": "New Customers",
            "action": "ONBOARD & NURTURE",
            "tactics": ["Welcome Email Series", "Product Tutorial", "Next Purchase Incentive", "Community"],
            "priority": "MEDIUM",
        },
        "Promising": {
            "color": "#F39C12",
            "label": "Promising",
            "action": "INCREASE FREQUENCY",
            "tactics": ["Bundle Offers", "Subscription Model", "Purchase Reminders", "Product Combos"],
            "priority": "MEDIUM",
        },
        "Hibernating": {
            "color": "#95A5A6",
            "label": "Hibernating",
            "action": "REACTIVATE",
            "tactics": ["Mass Email Campaign", "Special Promotion", "New Product Launch", "Win-back Offer"],
            "priority": "LOW",
        },
        "Lost": {
            "color": "#7F8C8D",
            "label": "Lost",
            "action": "LOW PRIORITY",
            "tactics": ["Cheap Mass Campaign", "Exit Survey", "Archive Segment", "Final Offer"],
            "priority": "LOW",
        },
        "Need Attention": {
            "color": "#FFAAA5",
            "label": "Need Attention",
            "action": "PREVENT CHURN",
            "tactics": ["Check-in Email", "Special Attention", "Small Gift", "Feedback Request"],
            "priority": "MEDIUM",
        },
    }

    for idx, segment in enumerate(segments_to_show):
        row = idx // 3
        col = idx % 3
        ax = fig.add_subplot(gs[row, col])

        seg_data = rfm[rfm["Segment"] == segment]
        info = segment_actions[segment]

        # Background
        ax.set_facecolor(info["color"])
        ax.set_alpha(0.1)

        # Remove axes
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_edgecolor(info["color"])
            spine.set_linewidth(4)

        # Content
        y_pos = 0.93

        # Header
        ax.text(
            0.5, y_pos, info["label"],
            ha="center", va="top", fontsize=16, fontweight="bold",
            bbox=dict(boxstyle="round", facecolor=info["color"], alpha=0.3, pad=0.5),
        )
        y_pos -= 0.13

        # Metrics
        ax.text(
            0.5, y_pos, f"{len(seg_data)} customers",
            ha="center", va="top", fontsize=13, fontweight="bold",
        )
        y_pos -= 0.08

        ax.text(
            0.5, y_pos, f"GBP {seg_data['Monetary'].sum() / 1000:.0f}k total revenue",
            ha="center", va="top", fontsize=13, fontweight="bold",
        )
        y_pos -= 0.08

        ax.text(
            0.5, y_pos,
            f"Average: GBP {seg_data['Monetary'].mean():.0f} per customer",
            ha="center", va="top", fontsize=10, style="italic",
        )
        y_pos -= 0.12

        # Divider line
        ax.plot([0.1, 0.9], [y_pos, y_pos], color=info["color"], linewidth=2, alpha=0.5)
        y_pos -= 0.06

        # Action
        ax.text(
            0.5, y_pos, info["action"],
            ha="center", va="top", fontsize=14, fontweight="bold",
            color=info["color"],
        )
        y_pos -= 0.12

        # Tactics
        ax.text(
            0.5, y_pos, "Recommended Actions:",
            ha="center", va="top", fontsize=10, fontweight="bold", style="italic",
        )
        y_pos -= 0.08

        for tactic in info["tactics"]:
            ax.text(0.5, y_pos, f"- {tactic}", ha="center", va="top", fontsize=10)
            y_pos -= 0.07

        # Priority badge
        priority_colors = {
            "CRITICAL": "#C0392B", "URGENT": "#E74C3C",
            "HIGH": "#F39C12", "MEDIUM": "#3498DB", "LOW": "#95A5A6",
        }
        ax.text(
            0.5, -0.12, f"PRIORITY: {info['priority']}",
            ha="center", va="center", fontsize=11, fontweight="bold",
            bbox=dict(
                boxstyle="round",
                facecolor=priority_colors[info["priority"]],
                edgecolor="black", linewidth=2, pad=0.5,
            ),
            color="white",
        )

        ax.set_xlim(0, 1)
        ax.set_ylim(-0.18, 1)

    save_figure(fig, output_dir, "4_rfm_action_cards.png")


# ------------------------------------------------------------------
# 5. K-Means Elbow Method
# ------------------------------------------------------------------

def plot_elbow_method(elbow_df, optimal_k, output_dir):
    """3-panel: elbow (inertia), silhouette, davies-bouldin."""
    fig, axes = plt.subplots(1, 3, figsize=(18, 5))
    fig.suptitle(
        "K-Means: Finding Optimal Number of Clusters",
        fontsize=16, fontweight="bold",
    )

    k_values = elbow_df["k"].values
    inertias = elbow_df["inertia"].values
    silhouette_scores = elbow_df["silhouette"].values
    davies_bouldin_scores = elbow_df["davies_bouldin"].values

    # --- Panel 1: Elbow Curve (Inertia) ---
    axes[0].plot(k_values, inertias, "bo-", linewidth=2, markersize=8)
    axes[0].set_xlabel("Number of Clusters (K)", fontsize=12, fontweight="bold")
    axes[0].set_ylabel("Inertia (Within-cluster sum of squares)", fontsize=12, fontweight="bold")
    axes[0].set_title("Elbow Method", fontsize=14, fontweight="bold")
    axes[0].grid(True, alpha=0.3)
    axes[0].axvline(x=optimal_k, color="red", linestyle="--", alpha=0.5, label=f"K={optimal_k}")
    axes[0].legend()

    # --- Panel 2: Silhouette Score ---
    axes[1].plot(k_values, silhouette_scores, "go-", linewidth=2, markersize=8)
    axes[1].set_xlabel("Number of Clusters (K)", fontsize=12, fontweight="bold")
    axes[1].set_ylabel("Silhouette Score", fontsize=12, fontweight="bold")
    axes[1].set_title("Silhouette Score (Higher = Better)", fontsize=14, fontweight="bold")
    axes[1].grid(True, alpha=0.3)
    best_k_sil = int(k_values[np.argmax(silhouette_scores)])
    axes[1].axvline(x=best_k_sil, color="red", linestyle="--", alpha=0.5, label=f"Best K={best_k_sil}")
    axes[1].axvline(x=optimal_k, color="orange", linestyle="--", alpha=0.5, label=f"K={optimal_k}")
    axes[1].legend()

    # --- Panel 3: Davies-Bouldin Score ---
    axes[2].plot(k_values, davies_bouldin_scores, "ro-", linewidth=2, markersize=8)
    axes[2].set_xlabel("Number of Clusters (K)", fontsize=12, fontweight="bold")
    axes[2].set_ylabel("Davies-Bouldin Score", fontsize=12, fontweight="bold")
    axes[2].set_title("Davies-Bouldin Score (Lower = Better)", fontsize=14, fontweight="bold")
    axes[2].grid(True, alpha=0.3)
    best_k_db = int(k_values[np.argmin(davies_bouldin_scores)])
    axes[2].axvline(x=best_k_db, color="red", linestyle="--", alpha=0.5, label=f"Best K={best_k_db}")
    axes[2].axvline(x=optimal_k, color="orange", linestyle="--", alpha=0.5, label=f"K={optimal_k}")
    axes[2].legend()

    fig.tight_layout()
    save_figure(fig, output_dir, "5_kmeans_elbow_method.png")


# ------------------------------------------------------------------
# 6. K-Means Final Comparison
# ------------------------------------------------------------------

def plot_kmeans_comparison(rfm, output_dir):
    """4-panel: K-Means 3D, RFM 3D, cluster size comparison,
    revenue comparison."""
    fig = plt.figure(figsize=(16, 12))

    kmeans_color_map = {
        "Inactive": "#95A5A6", "Regular": "#3498DB",
        "VIP Regulars": "#2ECC71", "Super VIPs": "#E74C3C",
    }

    # --- Panel 1: K-Means Clusters (3D) ---
    ax1 = fig.add_subplot(221, projection="3d")
    for label in ["Inactive", "Regular", "VIP Regulars", "Super VIPs"]:
        cluster_data = rfm[rfm["KMeans_Label"] == label]
        if len(cluster_data) == 0:
            continue
        ax1.scatter(
            cluster_data["Recency"],
            cluster_data["Frequency"],
            cluster_data["Monetary"],
            c=kmeans_color_map[label],
            label=label, s=50, alpha=0.6,
            edgecolors="black", linewidth=0.5,
        )
    ax1.set_xlabel("Recency (Days)", fontsize=11, fontweight="bold")
    ax1.set_ylabel("Frequency (Purchases)", fontsize=11, fontweight="bold")
    ax1.set_zlabel("Monetary (GBP)", fontsize=11, fontweight="bold")
    ax1.set_title("K-Means Clustering (K=4)", fontsize=14, fontweight="bold")
    ax1.legend(fontsize=9)

    # --- Panel 2: RFM Segments (top 4) (3D) ---
    ax2 = fig.add_subplot(222, projection="3d")
    top_segments = ["Champions", "Loyal Customers", "At Risk", "Lost"]
    segment_colors_map = {
        "Champions": "#2ECC71", "Loyal Customers": "#3498DB",
        "At Risk": "#E74C3C", "Lost": "#95A5A6",
    }
    for segment in top_segments:
        segment_data = rfm[rfm["Segment"] == segment]
        ax2.scatter(
            segment_data["Recency"],
            segment_data["Frequency"],
            segment_data["Monetary"],
            c=segment_colors_map[segment],
            label=segment, s=50, alpha=0.6,
            edgecolors="black", linewidth=0.5,
        )
    ax2.set_xlabel("Recency (Days)", fontsize=11, fontweight="bold")
    ax2.set_ylabel("Frequency (Purchases)", fontsize=11, fontweight="bold")
    ax2.set_zlabel("Monetary (GBP)", fontsize=11, fontweight="bold")
    ax2.set_title("RFM Segmentation (Top 4)", fontsize=14, fontweight="bold")
    ax2.legend(fontsize=9)

    # --- Panel 3: Cluster Size Comparison ---
    ax3 = fig.add_subplot(223)
    cluster_summary = pd.DataFrame({
        "K-Means": rfm["KMeans_Label"].value_counts(),
        "RFM Top-4": rfm[rfm["Segment"].isin(top_segments)]["Segment"].value_counts(),
    })
    cluster_summary.plot(kind="barh", ax=ax3, color=["#3498DB", "#2ECC71"])
    ax3.set_xlabel("Number of Customers", fontsize=11, fontweight="bold")
    ax3.set_title("Cluster Size Comparison", fontsize=14, fontweight="bold")
    ax3.legend(["K-Means", "RFM"])

    # --- Panel 4: Revenue Comparison ---
    ax4 = fig.add_subplot(224)
    kmeans_revenue = rfm.groupby("KMeans_Label")["Monetary"].sum() / 1000
    rfm_revenue = rfm.groupby("Segment")["Monetary"].sum().nlargest(4) / 1000

    x = np.arange(len(kmeans_revenue))
    width = 0.35
    ax4.bar(x - width / 2, kmeans_revenue.values, width, label="K-Means", color="#3498DB")
    ax4.bar(x + width / 2, rfm_revenue.values[:len(kmeans_revenue)], width, label="RFM", color="#2ECC71")

    ax4.set_ylabel("Revenue (GBP k)", fontsize=11, fontweight="bold")
    ax4.set_title("Revenue by Cluster/Segment", fontsize=14, fontweight="bold")
    ax4.set_xticks(x)
    ax4.set_xticklabels(kmeans_revenue.index, rotation=45, ha="right")
    ax4.legend()

    fig.tight_layout()
    save_figure(fig, output_dir, "6_kmeans_final_comparison.png")


# ------------------------------------------------------------------
# 7. Algorithm Comparison Dashboard
# ------------------------------------------------------------------

def plot_algorithm_comparison(comparison_df, hopkins_log, hopkins_yj, output_dir):
    """4-panel: silhouette comparison, davies-bouldin comparison,
    Hopkins statistic, BIC/AIC for GMM."""
    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    fig.suptitle(
        "Algorithm Comparison: K-Means vs GMM",
        fontsize=20, fontweight="bold", y=0.995,
    )

    algorithms = comparison_df["algorithm"].tolist()
    transforms = comparison_df["transform"].tolist()
    labels = [f"{a}\n({t})" for a, t in zip(algorithms, transforms)]
    colors = ["#3498DB", "#2ECC71", "#E74C3C", "#F39C12"]

    # --- Panel 1: Silhouette Score ---
    sil_values = comparison_df["silhouette"].tolist()
    bars = axes[0, 0].bar(labels, sil_values, color=colors, edgecolor="black", linewidth=1.5)
    axes[0, 0].set_ylabel("Silhouette Score", fontsize=12, fontweight="bold")
    axes[0, 0].set_title("Silhouette Score (Higher = Better)", fontsize=14, fontweight="bold")
    axes[0, 0].grid(True, alpha=0.3, axis="y")
    for bar, val in zip(bars, sil_values):
        axes[0, 0].text(
            bar.get_x() + bar.get_width() / 2, val + 0.01,
            f"{val:.3f}", ha="center", va="bottom", fontweight="bold", fontsize=11,
        )
    # Highlight best
    best_idx = sil_values.index(max(sil_values))
    bars[best_idx].set_edgecolor("#FFD700")
    bars[best_idx].set_linewidth(4)

    # --- Panel 2: Davies-Bouldin Score ---
    db_values = comparison_df["davies_bouldin"].tolist()
    bars2 = axes[0, 1].bar(labels, db_values, color=colors, edgecolor="black", linewidth=1.5)
    axes[0, 1].set_ylabel("Davies-Bouldin Score", fontsize=12, fontweight="bold")
    axes[0, 1].set_title("Davies-Bouldin Score (Lower = Better)", fontsize=14, fontweight="bold")
    axes[0, 1].grid(True, alpha=0.3, axis="y")
    for bar, val in zip(bars2, db_values):
        axes[0, 1].text(
            bar.get_x() + bar.get_width() / 2, val + 0.02,
            f"{val:.3f}", ha="center", va="bottom", fontweight="bold", fontsize=11,
        )
    best_db_idx = db_values.index(min(db_values))
    bars2[best_db_idx].set_edgecolor("#FFD700")
    bars2[best_db_idx].set_linewidth(4)

    # --- Panel 3: Hopkins Statistic ---
    hopkins_labels = ["log-transform", "Yeo-Johnson"]
    hopkins_values = [hopkins_log, hopkins_yj]
    bars3 = axes[1, 0].bar(
        hopkins_labels, hopkins_values,
        color=["#3498DB", "#E74C3C"], edgecolor="black", linewidth=1.5,
    )
    axes[1, 0].axhline(y=0.75, color="red", linestyle="--", alpha=0.7, label="Threshold (0.75)")
    axes[1, 0].axhline(y=0.5, color="gray", linestyle="--", alpha=0.5, label="Random (0.50)")
    axes[1, 0].set_ylabel("Hopkins Statistic", fontsize=12, fontweight="bold")
    axes[1, 0].set_title(
        "Clustering Tendency\n(>0.75 = strong clustering)", fontsize=14, fontweight="bold",
    )
    axes[1, 0].set_ylim(0, 1)
    axes[1, 0].legend(fontsize=10)
    axes[1, 0].grid(True, alpha=0.3, axis="y")
    for bar, val in zip(bars3, hopkins_values):
        axes[1, 0].text(
            bar.get_x() + bar.get_width() / 2, val + 0.02,
            f"{val:.3f}", ha="center", va="bottom", fontweight="bold", fontsize=13,
        )

    # --- Panel 4: BIC / AIC for GMM ---
    gmm_rows = comparison_df[comparison_df["algorithm"] == "GMM"]
    gmm_labels = [f"GMM\n({row['transform']})" for _, row in gmm_rows.iterrows()]
    bic_values = gmm_rows["bic"].tolist()
    aic_values = gmm_rows["aic"].tolist()

    x = np.arange(len(gmm_labels))
    width = 0.35
    axes[1, 1].bar(x - width / 2, bic_values, width, label="BIC", color="#3498DB", edgecolor="black")
    axes[1, 1].bar(x + width / 2, aic_values, width, label="AIC", color="#2ECC71", edgecolor="black")
    axes[1, 1].set_xticks(x)
    axes[1, 1].set_xticklabels(gmm_labels, fontsize=11)
    axes[1, 1].set_ylabel("Information Criterion", fontsize=12, fontweight="bold")
    axes[1, 1].set_title(
        "GMM Model Selection\n(BIC/AIC — Lower = Better)", fontsize=14, fontweight="bold",
    )
    axes[1, 1].legend(fontsize=11)
    axes[1, 1].grid(True, alpha=0.3, axis="y")

    fig.tight_layout()
    save_figure(fig, output_dir, "7_algorithm_comparison.png")


# ======================================================================
# Main pipeline
# ======================================================================

def main(argv=None):
    args = parse_args(argv)

    # ---- Setup ----
    started_at = datetime.now(timezone.utc)
    started_timer = time.perf_counter()
    input_path = Path(args.input).expanduser().resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"Input file not found: {input_path}")
    input_sha256 = sha256_file(input_path)
    run_paths = create_run_directory(args.output_root, args.run_id)

    print("=" * 60)
    print("RFM CUSTOMER SEGMENTATION PIPELINE")
    print("=" * 60)
    print(f"Input file:   {input_path}")
    print(f"Run ID:       {run_paths.run_id}")
    print(f"Run dir:      {run_paths.root}")
    print(f"K-Means K:    {args.k}")
    print()

    # ---- Step 1: Load data ----
    print("[1/5] Loading data ...")
    df = pd.read_csv(input_path)
    df["InvoiceDate"] = pd.to_datetime(df["InvoiceDate"])
    print(f"  Loaded {len(df):,} rows, {df['CustomerID'].nunique():,} unique customers")
    print()

    # ---- Step 2: Compute RFM, score, and segment ----
    print("[2/5] Computing RFM scores and segments ...")
    pipeline = RFMPipeline()
    rfm = pipeline.compute_rfm(df)
    rfm = pipeline.score_rfm(rfm)
    rfm = pipeline.segment_customers(rfm)
    print(f"  RFM table: {len(rfm):,} customers, {rfm['Segment'].nunique()} segments")
    print()

    # ---- Step 3: K-Means clustering ----
    print("[3/5] Running K-Means clustering ...")
    # Elbow analysis (K=2..15)
    elbow_df = pipeline.find_optimal_k(rfm)

    # Final clustering with chosen K
    rfm, kmeans_model, scaler, metrics = pipeline.cluster_kmeans(rfm, k=args.k)

    # Assign business names programmatically (sort by mean Monetary)
    cluster_mean_monetary = rfm.groupby("Cluster")["Monetary"].mean().sort_values()
    sorted_cluster_ids = cluster_mean_monetary.index.tolist()
    tier_names = ["Inactive", "Regular", "VIP Regulars", "Super VIPs"]
    # If k differs from 4, generate generic tier names
    if args.k != 4:
        tier_names = [f"Tier {i + 1}" for i in range(args.k)]
    kmeans_names = {
        cluster_id: tier_names[rank]
        for rank, cluster_id in enumerate(sorted_cluster_ids)
    }
    rfm["KMeans_Label"] = rfm["Cluster"].map(kmeans_names)

    print(f"  K-Means Silhouette Score:    {metrics['silhouette_score']:.3f}")
    print(f"  K-Means Davies-Bouldin Score: {metrics['davies_bouldin_score']:.3f}")
    print()

    # ---- Step 3b: Algorithm comparison ----
    print("[3b/6] Running algorithm comparison (K-Means vs GMM, log vs Yeo-Johnson) ...")
    comparison_df = pipeline.compare_algorithms(rfm, k=args.k)

    # Hopkins statistics
    scaled_log, _ = pipeline._preprocess_features(rfm, method="log")
    scaled_yj, _ = pipeline._preprocess_features(rfm, method="yeo-johnson")
    hopkins_log = pipeline.hopkins_statistic(scaled_log)
    hopkins_yj = pipeline.hopkins_statistic(scaled_yj)

    print()
    print("  Algorithm Comparison:")
    print(f"  {'Algorithm':<12} {'Transform':<14} {'Silhouette':>11} {'Davies-Bouldin':>15}")
    print("  " + "-" * 54)
    best_sil = comparison_df["silhouette"].max()
    for _, row in comparison_df.iterrows():
        marker = " <-- BEST" if row["silhouette"] == best_sil else ""
        print(
            f"  {row['algorithm']:<12} {row['transform']:<14} "
            f"{row['silhouette']:>11.3f} {row['davies_bouldin']:>15.3f}{marker}"
        )
    print()
    print(f"  Hopkins Statistic (log):        {hopkins_log:.3f}")
    print(f"  Hopkins Statistic (Yeo-Johnson): {hopkins_yj:.3f}")
    print()

    # ---- Step 4: Print summary table ----
    print("[4/6] Summary")
    print("-" * 60)
    print()

    # Segment summary
    segment_counts = rfm["Segment"].value_counts()
    segment_revenue = rfm.groupby("Segment")["Monetary"].sum()
    segment_avg = rfm.groupby("Segment")["Monetary"].mean()
    summary = pd.DataFrame({
        "Count": segment_counts,
        "Pct": (segment_counts / len(rfm) * 100).round(1),
        "Total_Revenue": segment_revenue.round(2),
        "Avg_Revenue": segment_avg.round(2),
    }).sort_values("Total_Revenue", ascending=False)
    print("RFM Segment Summary:")
    print(summary.to_string())
    print()

    # K-Means summary
    print("K-Means Cluster Summary:")
    for cluster_id in sorted_cluster_ids:
        name = kmeans_names[cluster_id]
        cluster_data = rfm[rfm["Cluster"] == cluster_id]
        count = len(cluster_data)
        mean_m = cluster_data["Monetary"].mean()
        total_rev = cluster_data["Monetary"].sum()
        print(
            f"  Cluster {cluster_id} -> {name:15s} | "
            f"{count:4d} customers | "
            f"Mean Monetary: GBP {mean_m:>10,.2f} | "
            f"Total: GBP {total_rev:>12,.2f}"
        )
    print()

    # ---- Step 5: Generate all 7 visualizations ----
    print("[5/6] Generating visualizations ...")
    visualization_dir = str(run_paths.visualizations)
    plot_segment_overview(rfm, visualization_dir)
    plot_executive_summary(rfm, visualization_dir)
    plot_3d_scatter(rfm, visualization_dir)
    plot_action_cards(rfm, visualization_dir)
    plot_elbow_method(elbow_df, args.k, visualization_dir)
    plot_kmeans_comparison(rfm, visualization_dir)
    plot_algorithm_comparison(comparison_df, hopkins_log, hopkins_yj, visualization_dir)

    # ---- Step 6: Export tables and metadata ----
    print("[6/6] Exporting tables and run metadata ...")
    export_summary = build_segment_summary(rfm)
    table_files = export_tables(
        run_paths,
        rfm,
        export_summary,
        elbow_df,
        comparison_df,
    )
    table_files.extend(export_transaction_tables(run_paths, df))
    image_files = sorted(run_paths.visualizations.glob("*.png"))
    if len(image_files) != 7:
        raise RuntimeError(f"Expected 7 visualization files, found {len(image_files)}")

    completed_at = datetime.now(timezone.utc)
    duration_seconds = time.perf_counter() - started_timer
    metadata_path = run_paths.metadata / "run_metadata.json"
    output_files = [*table_files, *image_files, metadata_path]
    metadata_payload = {
        "run_id": run_paths.run_id,
        "started_at_utc": started_at.isoformat(),
        "completed_at_utc": completed_at.isoformat(),
        "duration_seconds": duration_seconds,
        "input": {
            "path": str(input_path),
            "sha256": input_sha256,
            "rows": int(len(df)),
            "customers": int(df["CustomerID"].nunique(dropna=True)),
            "orders": int(df["InvoiceNo"].nunique(dropna=True)),
            "date_min": df["InvoiceDate"].min().isoformat(),
            "date_max": df["InvoiceDate"].max().isoformat(),
        },
        "parameters": {
            "input": args.input,
            "output_root": str(Path(args.output_root).expanduser().resolve()),
            "run_id": run_paths.run_id,
            "k": args.k,
        },
        "runtime": runtime_versions(),
        "results": {
            "rfm_customers": int(len(rfm)),
            "segments": int(rfm["Segment"].nunique()),
            "kmeans_metrics": metrics,
            "hopkins_log": hopkins_log,
            "hopkins_yeo_johnson": hopkins_yj,
            "algorithm_comparison_rows": int(len(comparison_df)),
        },
        "output_files": relative_manifest(run_paths.root, output_files),
    }
    write_metadata(run_paths, metadata_payload)

    print()
    print("=" * 60)
    print(f"Pipeline complete. Results saved to {run_paths.root}")
    print(f"Duration: {duration_seconds:.3f} seconds")
    print("=" * 60)
    return run_paths


if __name__ == "__main__":
    main()
