# RFM Customer Segmentation - ML-Driven Approach

> **Language:** English | [Deutsch](README.de.md)

[![Python](https://img.shields.io/badge/Python-3.11-blue.svg)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-71%20passed-brightgreen.svg)](https://github.com/leelesemann-sys/rfm-customer-segmentation/actions/workflows/test.yml)
[![Coverage](https://raw.githubusercontent.com/leelesemann-sys/rfm-customer-segmentation/main/.github/badges/coverage.svg)](https://github.com/leelesemann-sys/rfm-customer-segmentation/actions/workflows/test.yml)
[![CI](https://github.com/leelesemann-sys/rfm-customer-segmentation/actions/workflows/test.yml/badge.svg)](https://github.com/leelesemann-sys/rfm-customer-segmentation/actions/workflows/test.yml)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

> **End-to-end customer analytics pipeline** that segments 4,290 customers from £6.7M in retail transactions using rule-based RFM scoring and unsupervised clustering. Includes a systematic comparison of K-Means vs Gaussian Mixture Model across multiple preprocessing strategies.

---

## Business Impact

| Metric | Value |
|--------|-------|
| Total revenue analyzed | **£6.7M** across 394k transactions |
| Champions identified | **1,127 customers** generating £4.4M (65%) |
| Revenue at risk | **£575k** from 512 at-risk customers |
| Actionable segments | **10** with tailored marketing strategies |

---

## What Makes This Project Different

Most RFM analyses on this dataset stop at K-Means with default settings. This project goes further:

1. **Algorithm comparison** — K-Means vs GMM, systematically benchmarked
2. **Preprocessing comparison** — log-transform vs Yeo-Johnson power transform
3. **Statistical validation** — Hopkins statistic (0.956) proves data is clusterable *before* running algorithms
4. **Production-ready code** — Reusable `RFMPipeline` class, not just a notebook
5. **Tested and automated** — 71 tests (61 upstream + 10 product-output tests)
6. **Iterative development** — [v1.0](https://github.com/leelesemann-sys/rfm-customer-segmentation/releases/tag/v1.0) baseline, then [v2.0](https://github.com/leelesemann-sys/rfm-customer-segmentation/releases/tag/v2.0) with multi-algorithm comparison via [documented PR](https://github.com/leelesemann-sys/rfm-customer-segmentation/pull/1)

---

## Quick Start

```bash
git clone https://github.com/leelesemann-sys/rfm-customer-segmentation.git
cd rfm-customer-segmentation
pip install -r requirements.txt

python run_pipeline.py --output-root outputs/runs
python run_pipeline.py --output-root outputs/runs --run-id test_run
python run_pipeline.py --output-root outputs/runs --k 5
```

### 中文 Streamlit 看板

看板只读取本项目 `outputs/runs/<run_id>/` 下已经导出的结果，不会重新计算
RFM、修改分层规则，也不依赖参考项目、模拟数据或其他虚拟环境。它会默认选择
最近更新的 run，并支持切换 run、Segment 筛选、CustomerID 查询、K-Means 与
算法比较、7 张分析图片以及 CSV/JSON 下载。

```powershell
.venv\Scripts\python run_dashboard.py
```

也可直接启动：

```powershell
.venv\Scripts\python -m streamlit run app/app.py
```

未发现运行结果、文件缺失或字段格式错误时，页面会显示中文修复提示。界面布局
与交互方式参考 Amir 的 MIT 许可项目
[Data-Storytelling-Dashboard](https://github.com/AmirhosseinHonardoust/Data-Storytelling-Dashboard)；
完整归属说明、参考文件映射及许可证见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

---

## Isolated Run Outputs

Each pipeline execution creates a new immutable run directory. If a requested
`run_id` already exists, the command fails instead of overwriting prior results.

```text
outputs/runs/<run_id>/
├── tables/
│   ├── rfm_customers.csv
│   ├── segment_summary.csv
│   ├── kmeans_evaluation.csv
│   └── algorithm_comparison.csv
├── visualizations/
│   └── 7 PNG dashboards
└── metadata/
    └── run_metadata.json
```

The tracked `visualizations/` directory remains the upstream example gallery;
normal pipeline runs no longer write to it.

---

## Results

### RFM Segments (Rule-Based)

![RFM Segment Overview](visualizations/1_rfm_segment_overview.png)

| Priority | Segment | Customers | Revenue | Recommended Action |
|----------|---------|-----------|---------|-------------------|
| High | Champions | 1,127 | £4.4M | VIP programs, loyalty rewards |
| High | At Risk | 453 | £508k | Win-back campaigns, 20% discount |
| High | Can't Lose Them | 59 | £67k | Personal outreach, account managers |
| Medium | Loyal Customers | 802 | £994k | Upselling, cross-sell |
| Medium | New Customers | 136 | £44k | Onboarding, next purchase incentive |
| Low | Lost | 798 | £294k | Low-cost reactivation only |
| Low | Hibernating | 399 | £179k | Mass email campaigns |

### Algorithm Comparison

![Algorithm Comparison](visualizations/7_algorithm_comparison.png)

| Algorithm | Transform | Silhouette | Davies-Bouldin | Winner? |
|-----------|-----------|------------|----------------|---------|
| **K-Means** | **log** | **0.380** | **0.857** | **Best** |
| K-Means | Yeo-Johnson | 0.338 | 1.019 | |
| GMM | Yeo-Johnson | 0.197 | 1.768 | |
| GMM | log | 0.112 | 1.851 | |

**Key insight:** Contrary to Shobayo et al. (2023) who found GMM superior (Silhouette 0.80 vs 0.62), K-Means outperforms GMM on this dataset. The log-transform makes RFM features approximately spherical, which is exactly what K-Means assumes. GMM's flexibility (elliptical clusters) adds complexity without improving separation.

### K-Means Clusters (K=4)

![K-Means Comparison](visualizations/6_kmeans_final_comparison.png)

| Cluster | Size | Avg. Recency | Avg. Purchases | Avg. Spend |
|---------|------|-------------|----------------|------------|
| Inactive | 921 | 260 days | 1 | £356 |
| Regular | 1,341 | 59 days | 1 | £359 |
| VIP Regulars | 1,434 | 47 days | 4 | £1,442 |
| Super VIPs | 594 | 19 days | 15 | £6,457 |

### Dashboards

![Executive Summary](visualizations/2_rfm_executive_summary.png)
![K-Means Elbow](visualizations/5_kmeans_elbow_method.png)

---

## Methodology

```
Raw Data (541k rows)
    │
    ├── 1. Data Cleaning ──────────── 394k transactions retained (72.7%)
    ├── 2. RFM Aggregation ────────── 4,290 customer profiles
    ├── 3. Quintile Scoring ───────── R/F/M scores (1-5 scale)
    ├── 4. Rule-Based Segments ────── 10 business segments
    ├── 5. Hopkins Statistic ──────── 0.956 (clustering validated)
    ├── 6. Preprocessing ──────────── log-transform vs Yeo-Johnson
    ├── 7. Algorithm Comparison ───── K-Means vs GMM (4 combinations)
    └── 8. Best Model ─────────────── K-Means + log (Silhouette: 0.380)
```

---

## Tech Stack

| Category | Tools |
|----------|-------|
| Language | Python 3.11 |
| Data | pandas, numpy |
| ML | scikit-learn (K-Means, GMM, Hopkins, Yeo-Johnson) |
| Visualization | matplotlib, seaborn |
| Testing | pytest (71 tests: 61 upstream + 10 product-output tests) |
| CI/CD | GitHub Actions (Python 3.10, 3.11, 3.12) |

---

## Project Structure

```
rfm-customer-segmentation/
├── src/
│   ├── __init__.py
│   ├── rfm_pipeline.py               # Reusable pipeline class (K-Means, GMM, Hopkins)
│   └── result_exporter.py            # Isolated run directories and CSV/JSON exports
├── notebooks/
│   ├── 01_data_exploration.ipynb      # EDA & data cleaning
│   └── 02_rfm_analysis.ipynb         # RFM scoring & clustering
├── tests/
│   ├── conftest.py                    # Shared test fixtures (50 synthetic customers)
│   ├── test_pipeline.py               # 61 upstream unit tests
│   ├── test_result_exporter.py        # Isolated directory and export tests
│   └── test_run_pipeline_outputs.py   # Full output-isolation integration test
├── visualizations/                    # 7 publication-ready PNGs
├── outputs/runs/                       # Ignored, isolated runtime outputs
├── data/
│   └── online_retail_clean.csv.zip   # Cleaned dataset (394k transactions)
├── run_pipeline.py                    # CLI entrypoint (full pipeline + all visualizations)
├── .github/workflows/test.yml         # CI: tests + coverage badge
└── requirements.txt
```

---

## Dataset

**Source:** [UCI Machine Learning Repository — Online Retail](https://archive.ics.uci.edu/dataset/352/online+retail)
**Period:** Dec 2010 -- Dec 2011 (12.4 months)
**Size:** 541,909 transactions | 4,290 unique customers | UK-based (89.1%)

---

## Version History

| Version | What changed | PR |
|---------|-------------|-----|
| [v1.0](https://github.com/leelesemann-sys/rfm-customer-segmentation/releases/tag/v1.0) | Baseline: RFM + K-Means, 36 tests, CI | -- |
| [v2.0](https://github.com/leelesemann-sys/rfm-customer-segmentation/releases/tag/v2.0) | +GMM, +Yeo-Johnson, +Hopkins, 61 tests | [#1](https://github.com/leelesemann-sys/rfm-customer-segmentation/pull/1) |

---

## Future Enhancements

- [ ] Predictive CLV model (Random Forest / XGBoost)
- [ ] Churn prediction classifier
- [ ] Real-time segmentation API (FastAPI)
- [ ] Interactive dashboard (Streamlit or Power BI)

---

## Author

**Lee Christian Lesemann**
Azure AI Engineer | Customer Analytics Consultant
*Previous: Sanofi, CSL Behring, Abbott, Teva Pharmaceuticals, IQVIA*

[![LinkedIn](https://img.shields.io/badge/LinkedIn-Connect-blue)](https://www.linkedin.com/in/leelesemann)

---

## License

MIT License -- see [LICENSE](LICENSE) for details
